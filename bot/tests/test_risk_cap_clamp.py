"""RISK_CAP_HARD_CLAMP: realized risk-at-stop must not exceed MAX_RISK_PCT_CEILING.

Before this fix the ceiling reached the Risk Agent only as prompt text; the
risk_pct the agent RETURNED became position size unbounded
(coordinator.get_entry_decision: qty = equity * risk_pct / stop_width).
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.risk_cap import apply_risk_cap, realized_risk_frac  # noqa: E402

EQUITY = 1000.0
ENTRY = 50000.0
SL = 49000.0          # stop width 1000 -> qty 0.001 risks $1 = 0.1% of equity
CEILING = 0.005


@pytest.fixture
def ceiling_env(monkeypatch):
    monkeypatch.setenv("MAX_RISK_PCT_CEILING", str(CEILING))
    monkeypatch.delenv("RISK_CAP_HARD_CLAMP", raising=False)
    return monkeypatch


def _entry_decision(risk_data):
    """Run the real coordinator sizing path with a mocked LLM pipeline."""
    from llm.decision_types import LLMDecision, StrategyWeights
    from llm.agents.coordinator import AgentCoordinator
    from llm.agents.base import AgentOutput, AgentRole

    coord = AgentCoordinator()
    coord.get_trading_decision = MagicMock(return_value=LLMDecision(
        action="proceed", confidence=0.8, regime="trend",
        strategy_weights=StrategyWeights(), memory_update=None,
        notes="test", size_multiplier=1.0,
    ))
    coord.last_pipeline_results = {
        AgentRole.RISK: AgentOutput(role=AgentRole.RISK, data=risk_data),
        AgentRole.TRADE: AgentOutput(role=AgentRole.TRADE, data={"a": "go", "thesis": "t"}),
    }
    with patch("llm.agents.coordinator.get_coordinator"):
        return coord.get_entry_decision(
            signal_context={"symbol": "BTC", "side": "BUY", "entry": ENTRY, "sl": SL,
                            "tp1": 52000, "tp2": 54000, "confidence": 80, "atr": 500},
            market_context={},
            portfolio_context={"equity": EQUITY},
        )


# ── helper ──────────────────────────────────────────────────────────

def test_helper_clamps_when_on(ceiling_env):
    ceiling_env.setenv("RISK_CAP_HARD_CLAMP", "true")
    qty = 0.03  # 3% risk
    out = apply_risk_cap(qty, ENTRY, SL, EQUITY)
    assert out < qty
    assert realized_risk_frac(out, ENTRY, SL, EQUITY) == pytest.approx(CEILING)


def test_helper_unchanged_and_shadow_logged_when_off(ceiling_env, caplog):
    caplog.set_level(logging.INFO, logger="execution.risk_cap")
    qty = 0.03
    assert apply_risk_cap(qty, ENTRY, SL, EQUITY, context="t") == qty
    assert any("[RISK-CLAMP-SHADOW]" in r.getMessage() and "would clamp" in r.getMessage()
               for r in caplog.records)


@pytest.mark.parametrize("flag", ["true", "false"])
def test_helper_never_increases(ceiling_env, caplog, flag):
    ceiling_env.setenv("RISK_CAP_HARD_CLAMP", flag)
    caplog.set_level(logging.INFO, logger="execution.risk_cap")
    for qty in (0.0001, 0.001, 0.005):  # 0.01%, 0.1%, 0.5% (at ceiling)
        assert apply_risk_cap(qty, ENTRY, SL, EQUITY) == qty
    # degenerate inputs: fail-neutral, unchanged
    assert apply_risk_cap(0.03, ENTRY, SL, 0.0) == 0.03
    assert apply_risk_cap(0.03, ENTRY, 0.0, EQUITY) == 0.03
    assert apply_risk_cap(-1.0, ENTRY, SL, EQUITY) == -1.0
    assert not any("would clamp" in r.getMessage() for r in caplog.records)


# ── coordinator: agent's risk_pct -> position size ──────────────────

def test_agent_over_cap_risk_pct_is_clamped_when_on(ceiling_env):
    ceiling_env.setenv("RISK_CAP_HARD_CLAMP", "true")
    d = _entry_decision({"leverage": 2.0, "risk_pct": 0.03})  # agent ignores 0.5% ceiling
    assert d.action == "go"
    assert realized_risk_frac(d.position_qty, ENTRY, SL, EQUITY) == pytest.approx(CEILING)
    assert d.risk_pct == pytest.approx(CEILING)


def test_missing_risk_pct_fallback_is_clamped_when_on(ceiling_env):
    # No risk_pct -> legacy fallback 10% * sz (= 20% here). Must also be capped.
    ceiling_env.setenv("RISK_CAP_HARD_CLAMP", "true")
    d = _entry_decision({"leverage": 2.0, "sz": 2.0})
    assert realized_risk_frac(d.position_qty, ENTRY, SL, EQUITY) == pytest.approx(CEILING)


def test_agent_over_cap_unchanged_and_shadow_logged_when_off(ceiling_env, caplog):
    caplog.set_level(logging.INFO, logger="execution.risk_cap")
    d = _entry_decision({"leverage": 2.0, "risk_pct": 0.03})
    # byte-identical legacy sizing: qty = equity * risk_pct / stop_width
    assert d.position_qty == pytest.approx(EQUITY * 0.03 / (ENTRY - SL))
    assert d.risk_pct == pytest.approx(0.03)
    assert any("[RISK-CLAMP-SHADOW]" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("flag", ["true", "false"])
def test_agent_under_cap_never_changed(ceiling_env, flag):
    ceiling_env.setenv("RISK_CAP_HARD_CLAMP", flag)
    d = _entry_decision({"leverage": 2.0, "risk_pct": 0.003})
    assert d.position_qty == pytest.approx(EQUITY * 0.003 / (ENTRY - SL))
    assert d.risk_pct == pytest.approx(0.003)


def test_final_order_point_is_wired():
    """The pre-order clamp in multi_strategy_main (after the LIVING-EDGE mult,
    which can push an obedient 0.5% agent to 0.75%) must call apply_risk_cap
    before order_executor.open_position on the LLM-first path."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "multi_strategy_main.py"),
               encoding="utf-8").read()
    i_edge = src.index("LIVING EDGE SIZING (2026-07-16): LLM-FIRST path")
    i_cap = src.index("_apply_risk_cap(", i_edge)
    i_order = src.index("self.order_executor.open_position(", i_edge)
    assert i_edge < i_cap < i_order


# --- laptop red-team 126 -----------------------------------------------------------------------------------------
def test_ceiling_fails_strict_not_loose(monkeypatch, caplog):
    from execution import risk_cap
    for bad in (None, "", "abc", "0", "-1"):
        if bad is None:
            monkeypatch.delenv("MAX_RISK_PCT_CEILING", raising=False)
        else:
            monkeypatch.setenv("MAX_RISK_PCT_CEILING", bad)
        with caplog.at_level(logging.WARNING):
            assert risk_cap.risk_ceiling() == 0.005
    assert "strict fallback" in caplog.text


def test_missing_stop_is_visible_not_silent(ceiling_env, caplog, monkeypatch):
    from execution import risk_cap
    monkeypatch.setenv("RISK_CAP_HARD_CLAMP", "true")
    with caplog.at_level(logging.WARNING):
        assert risk_cap.apply_risk_cap(10.0, 100.0, 0.0, 1000.0, context="t") == 10.0
        assert risk_cap.apply_risk_cap(10.0, 100.0, 100.0, 1000.0, context="t") == 10.0
    assert caplog.text.count("RISK-CLAMP-BLIND") == 2


def test_internal_error_logs_at_warning(ceiling_env, caplog, monkeypatch):
    from execution import risk_cap
    monkeypatch.setattr(risk_cap, "realized_risk_frac", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level(logging.WARNING):
        assert risk_cap.apply_risk_cap(10.0, 100.0, 90.0, 1000.0) == 10.0
    assert "cap NOT applied" in caplog.text


def test_side_mult_cap_and_min_notional_skip_are_wired():
    src = (Path(__file__).resolve().parents[1] / "multi_strategy_main.py").read_text(encoding="utf-8")
    assert "LIVING_EDGE_MULT_CAP" in src and "RISK-CLAMP-SKIP" in src
