"""Tests for llm/living_conf_floor.py and its wiring into llm/risk_gating.py.

Guards against a repeat of the 45-day silent drought (2026-07-29 -> 2026-09-12):
risk_gating Rule 2's hardcoded 0.60 confidence floor became an absolute wall
once the DEFABRICATE_* flags removed confidence inflation and the ensemble's
honest scale dropped to ~0.20-0.55. The bot stayed healthy and took zero trades.

Every test isolates the on-disk store via monkeypatch and MUST NOT touch the
real bot/data/llm_conf_distribution.json.
"""
from __future__ import annotations

import time

import pytest

from llm import living_conf_floor as lcf


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the module at a temp store and reset its in-memory state."""
    monkeypatch.setattr(lcf, "_STORE", str(tmp_path / "conf_dist.json"))
    monkeypatch.setattr(lcf, "_obs", [])
    monkeypatch.setattr(lcf, "_dirty", False)
    monkeypatch.setattr(lcf, "_last_flush", 0.0)
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})
    monkeypatch.delenv("LIVING_CONF_FLOOR", raising=False)
    monkeypatch.delenv("LIVING_CONF_FLOOR_PCTL", raising=False)
    yield
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})


def _seed(values, now=None):
    now = now or time.time()
    lcf._obs = [[now, float(v)] for v in values]
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})


# ---------------------------------------------------------------- flag off


def test_disabled_returns_legacy_floor():
    _seed([0.3] * 100)
    assert lcf.base_floor(0.60) == 0.60


def test_disabled_leaves_sibling_thresholds_untouched():
    _seed([0.3] * 100)
    assert lcf.scaled(0.70) == 0.70
    assert lcf.scaled(0.68) == 0.68
    assert lcf.scaled(0.65) == 0.65


# ------------------------------------------------------------ fail-closed


def test_thin_evidence_falls_back_to_legacy(monkeypatch):
    """No data must never mean a looser gate."""
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.35] * (lcf.MIN_N - 1))
    assert lcf.base_floor(0.60) == 0.60


def test_exactly_min_n_activates(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.35] * lcf.MIN_N)
    assert lcf.base_floor(0.60) < 0.60


def test_empty_store_falls_back(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([])
    assert lcf.base_floor(0.60) == 0.60


# ------------------------------------------------------------- clamping


def test_never_opens_below_absolute_minimum(monkeypatch):
    """A collapsed scale (everything near zero) must not open the gate to ~0."""
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.01] * 100)
    assert lcf.base_floor(0.60) == lcf.FLOOR_MIN


def test_never_stricter_than_legacy(monkeypatch):
    """A re-inflated scale must not make the gate tighter than the 0.60 it replaced."""
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.95] * 100)
    assert lcf.base_floor(0.60) == 0.60


# ------------------------------------------------------------- percentile


def test_floor_is_the_requested_percentile(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "90")
    # 0.31 .. 0.55, 50 evenly spaced values; P90 of the index range.
    vals = [0.31 + i * 0.005 for i in range(50)]
    _seed(vals)
    expected = sorted(vals)[int(round(0.90 * 49))]
    assert lcf.base_floor(0.60) == pytest.approx(expected, abs=1e-9)


def test_higher_percentile_is_stricter(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    vals = [0.30 + i * 0.004 for i in range(60)]
    _seed(vals)
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "70")
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})
    loose = lcf.base_floor(0.60)
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "95")
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})
    strict = lcf.base_floor(0.60)
    assert strict > loose


def test_percentile_env_is_clamped_to_sane_range(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "400")
    assert lcf.percentile_target() == 99.0
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "-5")
    assert lcf.percentile_target() == 50.0
    monkeypatch.setenv("LIVING_CONF_FLOOR_PCTL", "not-a-number")
    assert lcf.percentile_target() == 90.0


# ------------------------------------------------------- sibling scaling


def test_siblings_scale_with_the_base_and_stay_ordered(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.40] * 100)                      # -> base floor 0.40, factor 2/3
    base = lcf.base_floor(0.60)
    assert base == pytest.approx(0.40)
    panic, streak, flip = lcf.scaled(0.70), lcf.scaled(0.68), lcf.scaled(0.65)
    # Each stays above the base floor and preserves its relative ordering.
    assert base < flip < streak < panic
    assert panic == pytest.approx(0.70 * (0.40 / 0.60))


def test_siblings_never_loosen_past_their_legacy_value(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.95] * 100)
    assert lcf.scaled(0.70) == 0.70


def test_siblings_respect_the_absolute_minimum(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.01] * 100)                      # base clamps to FLOOR_MIN
    assert lcf.scaled(0.65) >= lcf.FLOOR_MIN


# -------------------------------------------------------------- recording


def test_record_ignores_flat_and_junk(monkeypatch):
    lcf.record(0.5, "flat")
    lcf.record("banana", "proceed")
    lcf.record(None, "proceed")
    lcf.record(1.5, "proceed")
    lcf.record(-0.2, "proceed")
    assert lcf._obs == []


def test_record_persists_and_reloads(monkeypatch):
    lcf.record(0.42, "proceed")
    lcf.flush()
    monkeypatch.setattr(lcf, "_obs", None)   # force a reload from disk
    assert [c for _, c in lcf._load()] == [pytest.approx(0.42)]


def test_window_is_age_bounded(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    now = time.time()
    stale = [[now - lcf.MAX_AGE_S - 60, 0.90] for _ in range(100)]
    fresh = [[now, 0.35] for _ in range(lcf.MIN_N)]
    lcf._obs = stale + fresh
    lcf._cache.update({"floor": None, "at": 0.0, "n": None})
    # The stale 0.90s must not drag the floor up.
    assert lcf.base_floor(0.60) == pytest.approx(0.35)


def test_window_is_count_bounded():
    now = time.time()
    lcf._obs = [[now, 0.4] for _ in range(lcf.MAX_OBS + 50)]
    lcf._prune(now)
    assert len(lcf._obs) == lcf.MAX_OBS


# ------------------------------------------------------ risk_gating wiring


def _decision(conf, action="proceed", regime="trend"):
    from llm.decision_types import LLMDecision, StrategyWeights
    return LLMDecision(
        action=action,
        confidence=conf,
        regime=regime,
        size_multiplier=1.0,
        strategy_weights=StrategyWeights(),
        memory_update=None,
        notes="test",
    )


def _risk():
    from llm.risk_gating import RiskContext
    return RiskContext(
        daily_pnl=0.0, max_daily_loss=500.0, equity=5000.0,
        max_leverage=5.0, current_leverage=0.0, volatility=1.0,
        max_volatility=10.0, open_positions=0, max_positions=3,
        circuit_breaker_active=False, consecutive_losses=0,
    )


def test_gate_still_rejects_below_living_floor(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.40] * 100)
    from llm.risk_gating import gate_decision
    res = gate_decision(_decision(0.31), _risk())
    assert not res.allowed and "confidence_too_low" in res.reason


def test_gate_admits_the_decision_the_hardcoded_wall_blocked(monkeypatch):
    """The regression this whole module exists for: a real 0.52 call."""
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.30 + i * 0.002 for i in range(100)])   # live-shaped scale, P90 ~0.48
    from llm.risk_gating import gate_decision
    res = gate_decision(_decision(0.52), _risk())
    assert res.allowed, res.reason


def test_gate_with_flag_off_is_byte_for_byte_legacy(monkeypatch):
    monkeypatch.delenv("LIVING_CONF_FLOOR", raising=False)
    _seed([0.30] * 200)
    from llm.risk_gating import gate_decision
    assert not gate_decision(_decision(0.52), _risk()).allowed
    assert gate_decision(_decision(0.61), _risk()).allowed


def test_circuit_breaker_still_wins_over_a_loosened_floor(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    _seed([0.35] * 100)
    from llm.risk_gating import gate_decision
    risk = _risk()
    risk.circuit_breaker_active = True
    res = gate_decision(_decision(0.55), risk)
    assert not res.allowed and res.reason == "circuit_breaker_active"


def test_flat_is_never_recorded_by_the_gate(monkeypatch):
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    from llm.risk_gating import gate_decision
    gate_decision(_decision(0.10, action="flat"), _risk())
    assert lcf._obs == []


def test_gate_records_even_when_it_rejects(monkeypatch):
    """The distribution must not be survivor-biased."""
    monkeypatch.setenv("LIVING_CONF_FLOOR", "true")
    from llm.risk_gating import gate_decision
    gate_decision(_decision(0.22), _risk())
    assert [c for _, c in lcf._obs] == [pytest.approx(0.22)]
