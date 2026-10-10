"""ADAPTIVE_STOPS: forecast-sized stop/target at unchanged dollar risk (default off)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import multi_strategy_main as msm


def _bot_cls():
    for name in dir(msm):
        obj = getattr(msm, name)
        if isinstance(obj, type) and hasattr(obj, "_adaptive_stop"):
            return obj
    raise RuntimeError("no class with _adaptive_stop")


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    d = tmp_path / "data" / "hivemind" / "state"
    d.mkdir(parents=True)
    fake_file = tmp_path / "multi_strategy_main.py"
    monkeypatch.setattr(msm.os.path, "abspath", lambda p: str(fake_file) if str(p).endswith("multi_strategy_main.py") else p)
    return d


def _write(d, sym, stop_pct, tgt_pct, age_min=5):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat(timespec="seconds")
    (d / f"{sym}.json").write_text(json.dumps({"updated": ts, "risk": {
        "long": {"stop_pct": stop_pct, "target_pct": tgt_pct}, "short": {"stop_pct": stop_pct, "target_pct": tgt_pct}}}))


def _call(*a):
    cls = _bot_cls()
    return cls._adaptive_stop(object.__new__(cls), *a)


def test_widens_stop_and_keeps_dollar_risk(state_dir):
    _write(state_dir, "BTC", 4.0, 2.0)
    sl, tp1, qty = _call("BTC", "LONG", 100.0, 99.0, 101.5, 10.0, "t")
    assert sl == pytest.approx(96.0)
    assert tp1 == pytest.approx(101.5)   # stop only: signal target kept (owner 2026-10-10)
    assert qty * (100.0 - sl) == pytest.approx(10.0 * (100.0 - 99.0))   # same dollar risk


def test_short_side_mirrors(state_dir):
    _write(state_dir, "ETH", 4.0, 2.0)
    sl, tp1, qty = _call("ETH", "SHORT", 100.0, 101.0, 98.5, 10.0, "t")
    assert sl == pytest.approx(104.0) and tp1 == pytest.approx(98.5)
    assert qty == pytest.approx(2.5)


def test_never_tightens(state_dir):
    _write(state_dir, "SOL", 0.5, 0.25)
    assert _call("SOL", "LONG", 100.0, 98.0, 103.0, 10.0, "t") == (98.0, 103.0, 10.0)


def test_stale_reading_keeps_signal_stop(state_dir):
    _write(state_dir, "XRP", 4.0, 2.0, age_min=120)
    assert _call("XRP", "LONG", 100.0, 99.0, 101.5, 10.0, "t") == (99.0, 101.5, 10.0)


def test_missing_file_raises_for_caller_fallback(state_dir):
    with pytest.raises(FileNotFoundError):
        _call("NEAR", "LONG", 100.0, 99.0, 101.5, 10.0, "t")


def test_target_opt_in(state_dir, monkeypatch):
    monkeypatch.setenv("ADAPTIVE_STOPS_TARGET", "true")
    _write(state_dir, "BTC", 4.0, 2.0)
    sl, tp1, qty = _call("BTC", "LONG", 100.0, 99.0, 101.5, 10.0, "t")
    assert tp1 == pytest.approx(102.0)
