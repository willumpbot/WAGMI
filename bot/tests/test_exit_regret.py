"""Tests for analytics.exit_regret — measurement-only exit counterfactual.

Run: cd bot && pytest tests/test_exit_regret.py -v
"""
import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from analytics.exit_regret import ExitRegretEngine, _HORIZONS_H


class _FakeFetcher:
    """Deterministic price source: returns 1h candles from a fixed close path.

    Path: a LONG exits at 100 and price RECOVERS to 101/102/104 at +1/2/4h.
    """
    def __init__(self, base_ts, symbol_to_closes):
        self._base = base_ts
        self._closes = symbol_to_closes  # {symbol: [(dt, close), ...]}

    def fetch_ohlcv(self, symbol, coin_id, timeframe):
        rows = self._closes.get(symbol, [])
        return pd.DataFrame({"time": [r[0] for r in rows], "close": [r[1] for r in rows]})


def _write_close(path, **kw):
    with open(path, "a") as f:
        f.write(json.dumps(kw) + "\n")


def test_regret_long_recovers_positive(tmp_path):
    close_ts = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    closes_file = tmp_path / "exit_closes.jsonl"
    scores_file = tmp_path / "exit_regret_scores.jsonl"

    _write_close(
        str(closes_file),
        decision_id="abc123", ts=close_ts.isoformat(), symbol="BTC",
        side="LONG", exit_type="EARLY_EXIT", entry=98.0, exit_price=100.0,
        qty=1.0, leverage=1.0, pnl=2.0, regime="trend", strategy="x", mfe_pct=2.0,
    )

    # 1h candles at +1h/+2h/+4h after the close, price rising (recovery).
    candles = [
        (close_ts + timedelta(hours=1), 101.0),
        (close_ts + timedelta(hours=2), 102.0),
        (close_ts + timedelta(hours=3), 103.0),
        (close_ts + timedelta(hours=4), 104.0),
    ]
    eng = ExitRegretEngine(
        closes_file=str(closes_file), scores_file=str(scores_file),
        price_fetcher=_FakeFetcher(close_ts, {"BTC": candles}),
    )

    # Freeze 'now' well past +4h maturity by scoring with a fetcher whose data is
    # historical; resolve_pending uses real now() which is in 2026 >> close_ts.
    n = eng.resolve_pending()
    assert n == 1

    scores = [json.loads(l) for l in open(str(scores_file)) if l.strip()]
    assert len(scores) == 1
    s = scores[0]
    # LONG, price rose: regret must be positive at every horizon.
    assert s["regret_1h_pct"] == pytest.approx(1.0, abs=1e-6)
    assert s["regret_2h_pct"] == pytest.approx(2.0, abs=1e-6)
    assert s["regret_4h_pct"] == pytest.approx(4.0, abs=1e-6)
    assert s["recovered"] is True

    # Idempotency: re-running scores nothing new.
    assert eng.resolve_pending() == 0

    agg = eng.get_aggregates()
    assert agg["total_scored"] == 1
    part = agg["partitions"][0]
    assert (part["symbol"], part["side"], part["regime"], part["exit_type"]) == (
        "BTC", "LONG", "trend", "EARLY_EXIT")
    assert part["avg_regret_pct"] == pytest.approx(4.0, abs=1e-6)  # uses +4h


def test_regret_short_sign_and_justified_exit(tmp_path):
    close_ts = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    closes_file = tmp_path / "exit_closes.jsonl"
    scores_file = tmp_path / "exit_regret_scores.jsonl"
    _write_close(
        str(closes_file),
        decision_id="short1", ts=close_ts.isoformat(), symbol="ETH",
        side="SHORT", exit_type="SL", entry=110.0, exit_price=100.0,
        qty=1.0, leverage=1.0, pnl=-10.0, regime="panic", strategy="y", mfe_pct=0.0,
    )
    # After a SHORT is stopped out at 100, price keeps RISING (against short) =>
    # negative regret (exit justified).
    candles = [
        (close_ts + timedelta(hours=1), 101.0),
        (close_ts + timedelta(hours=2), 103.0),
        (close_ts + timedelta(hours=4), 105.0),
    ]
    eng = ExitRegretEngine(
        closes_file=str(closes_file), scores_file=str(scores_file),
        price_fetcher=_FakeFetcher(close_ts, {"ETH": candles}),
    )
    assert eng.resolve_pending() == 1
    s = [json.loads(l) for l in open(str(scores_file)) if l.strip()][0]
    # SHORT, price rose above exit => side_sign=-1 => negative regret.
    assert s["regret_4h_pct"] == pytest.approx(-5.0, abs=1e-6)
    assert s["recovered"] is False


def test_immature_close_not_scored(tmp_path):
    # Close stamped 'now' — +4h candle cannot exist yet => not scored.
    now = datetime.now(timezone.utc)
    closes_file = tmp_path / "exit_closes.jsonl"
    scores_file = tmp_path / "exit_regret_scores.jsonl"
    _write_close(
        str(closes_file),
        decision_id="fresh1", ts=now.isoformat(), symbol="BTC",
        side="LONG", exit_type="TP2", entry=98.0, exit_price=100.0,
        qty=1.0, leverage=1.0, pnl=2.0, regime="trend", strategy="x", mfe_pct=2.0,
    )
    eng = ExitRegretEngine(
        closes_file=str(closes_file), scores_file=str(scores_file),
        price_fetcher=_FakeFetcher(now, {"BTC": []}),
    )
    assert eng.resolve_pending() == 0
    assert not os.path.exists(str(scores_file)) or os.path.getsize(str(scores_file)) == 0
