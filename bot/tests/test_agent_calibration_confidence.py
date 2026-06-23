"""Proves per-agent calibration records each agent's OWN stated confidence and
directional-correctness outcomes — not confidence:0.0 and not PnL win/loss."""
import json
import os
import tempfile
import importlib

import pytest


@pytest.fixture
def fresh_ledger(monkeypatch, tmp_path):
    """Point the calibration ledger at a temp file and reset its singleton."""
    import llm.agents.calibration_ledger as cl
    cal_path = os.path.join(str(tmp_path), "agent_calibration.json")
    monkeypatch.setattr(cl, "_CALIBRATION_PATH", cal_path)
    cl._ledger = None  # force singleton rebuild against temp path
    yield cl
    cl._ledger = None


def _outcomes(ledger, key):
    bucket = ledger._buckets.get(key)
    return bucket.outcomes if bucket else []


def test_per_agent_confidence_is_recorded_not_zero(fresh_ledger):
    from llm.agents.learning_integration import _record_agent_calibration

    trade_data = {
        "regime": "trend",
        "side": "BUY",
        "pnl": -5.0,            # LOSS — must NOT drive the `correct` boolean
        "price_move_pct": 1.2,  # price actually moved up >0.5% -> trend correct
        "confidence": 0.0,       # blended consensus is 0 (the old bug source)
        "agent_confidences": {
            "trade": 0.72,
            "regime": 0.66,
            "critic": 0.40,
        },
        "notes": "",
    }
    # thesis_correct=True: directional thesis was right even though trade lost.
    _record_agent_calibration(trade_data, thesis_correct=True)

    ledger = fresh_ledger.get_calibration_ledger()

    trade_outs = _outcomes(ledger, "trade:trend")
    assert len(trade_outs) == 1
    # The Trade Agent's OWN confidence (0.72), NOT 0.0, NOT the blended 0.0:
    assert trade_outs[0]["confidence"] == pytest.approx(0.72, abs=1e-3)
    # correct is the directional thesis, not the PnL loss:
    assert trade_outs[0]["correct"] is True

    regime_outs = _outcomes(ledger, "regime:trend")
    assert len(regime_outs) == 1
    # Regime Agent's own confidence, not the hardcoded 0.5 placeholder:
    assert regime_outs[0]["confidence"] == pytest.approx(0.66, abs=1e-3)
    # trend regime + realized +1.2% move => regime classification was correct,
    # independent of the trade losing money.
    assert regime_outs[0]["correct"] is True


def test_avg_confidence_and_brier_nonzero(fresh_ledger):
    from llm.agents.learning_integration import _record_agent_calibration

    for tc in (True, False, True):
        _record_agent_calibration(
            {
                "regime": "trend",
                "side": "BUY",
                "pnl": 1.0,
                "price_move_pct": 0.8,
                "confidence": 0.0,
                "agent_confidences": {"trade": 0.6, "regime": 0.6},
                "notes": "",
            },
            thesis_correct=tc,
        )
    ledger = fresh_ledger.get_calibration_ledger()
    bucket = ledger._buckets["trade:trend"]
    # avg_confidence must reflect the real 0.6, not the corrupt 0.0:
    assert bucket.avg_confidence == pytest.approx(0.6, abs=1e-3)
    # brier is now computed from real confidence, not the degenerate 0.0 case:
    assert bucket.brier_score > 0.0


def test_falls_back_to_blended_when_no_agent_conf(fresh_ledger):
    from llm.agents.learning_integration import _record_agent_calibration
    # No agent_confidences -> use blended (normalized 0-100 -> 0-1).
    _record_agent_calibration(
        {
            "regime": "trend",
            "side": "BUY",
            "pnl": 1.0,
            "price_move_pct": 0.9,
            "confidence": 70.0,  # 0-100 scale
            "notes": "",
        },
        thesis_correct=True,
    )
    ledger = fresh_ledger.get_calibration_ledger()
    trade_outs = _outcomes(ledger, "trade:trend")
    assert trade_outs[0]["confidence"] == pytest.approx(0.70, abs=1e-3)
