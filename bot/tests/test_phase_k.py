"""Tests for PHASE K: Multi-LLM Ensemble (providers + llm_ensemble)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from llm.decision_types import LLMDecision, StrategyWeights
from llm.providers import (
    LLMProvider, PERSONAS, get_provider_config, get_active_personas,
)
from llm.llm_ensemble import aggregate_decisions, get_disagreement_metrics


# ── Provider Tests ──────────────────────────────────────────


def test_llm_provider_dataclass():
    p = LLMProvider(name="test", model="m", api_key_env="TEST_KEY", weight=0.9)
    assert p.name == "test"
    assert p.model == "m"
    assert p.weight == 0.9
    assert p.enabled is True
    assert p.max_retries == 2
    assert p.timeout_s == 30


def test_provider_api_key_from_env(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret123")
    p = LLMProvider(name="x", api_key_env="MY_KEY")
    assert p.api_key == "secret123"


def test_provider_api_key_missing():
    p = LLMProvider(name="x", api_key_env="NONEXISTENT_KEY_XYZ")
    assert p.api_key == ""


def test_personas_have_required_keys():
    for name, persona in PERSONAS.items():
        assert "description" in persona, f"{name} missing description"
        assert "prompt_modifier" in persona, f"{name} missing prompt_modifier"
        assert "weight" in persona, f"{name} missing weight"
        assert isinstance(persona["weight"], (int, float))


def test_get_provider_config_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SECONDARY_LLM_API_KEY", raising=False)
    providers = get_provider_config()
    assert providers == []


def test_get_provider_config_primary_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "pk_test")
    monkeypatch.delenv("SECONDARY_LLM_API_KEY", raising=False)
    providers = get_provider_config()
    assert len(providers) == 1
    assert providers[0].name == "primary"
    assert providers[0].weight == 1.0


def test_get_provider_config_both(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "pk_test")
    monkeypatch.setenv("SECONDARY_LLM_API_KEY", "sk_test")
    providers = get_provider_config()
    assert len(providers) == 2
    assert providers[1].name == "secondary"
    assert providers[1].weight == 0.8


def test_get_active_personas_empty(monkeypatch):
    monkeypatch.delenv("LLM_PERSONAS", raising=False)
    assert get_active_personas() == []


def test_get_active_personas_valid(monkeypatch):
    monkeypatch.setenv("LLM_PERSONAS", "risk_off,swing")
    result = get_active_personas()
    assert result == ["risk_off", "swing"]


def test_get_active_personas_filters_invalid(monkeypatch):
    monkeypatch.setenv("LLM_PERSONAS", "risk_off,fake_persona,scalper")
    result = get_active_personas()
    assert result == ["risk_off", "scalper"]


# ── Ensemble Tests ──────────────────────────────────────────


def _make_decision(action="proceed", confidence=0.8, regime="trend",
                   size_multiplier=1.0, notes="test"):
    return LLMDecision(
        action=action,
        confidence=confidence,
        regime=regime,
        strategy_weights=StrategyWeights(),
        memory_update=None,
        notes=notes,
        size_multiplier=size_multiplier,
    )


def test_aggregate_empty():
    assert aggregate_decisions([]) is None


def test_aggregate_no_valid():
    assert aggregate_decisions([{"decision": None}]) is None


def test_aggregate_single_passthrough():
    d = _make_decision(action="flat", confidence=0.3)
    result = aggregate_decisions([{"decision": d, "weight": 1.0, "name": "p"}])
    assert result is not None
    assert result.action == "flat"
    assert result.confidence == 0.3


def test_aggregate_unanimous_proceed():
    d1 = _make_decision(action="proceed", confidence=0.8, size_multiplier=1.2)
    d2 = _make_decision(action="proceed", confidence=0.6, size_multiplier=0.8)
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "primary"},
        {"decision": d2, "weight": 0.8, "name": "secondary"},
    ]
    result = aggregate_decisions(decisions)
    assert result is not None
    assert result.action == "proceed"
    # Weighted avg confidence: (0.8*1.0 + 0.6*0.8) / 1.8 = 1.28 / 1.8 ~ 0.711
    assert 0.70 < result.confidence < 0.72
    # Weighted avg size: (1.2*1.0 + 0.8*0.8) / 1.8 = 1.84 / 1.8 ~ 1.022
    assert 1.01 < result.size_multiplier < 1.04


def test_aggregate_strong_majority():
    d1 = _make_decision(action="proceed", confidence=0.9)
    d2 = _make_decision(action="flat", confidence=0.4)
    d3 = _make_decision(action="proceed", confidence=0.7)
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "a"},
        {"decision": d2, "weight": 0.5, "name": "b"},
        {"decision": d3, "weight": 1.0, "name": "c"},
    ]
    result = aggregate_decisions(decisions)
    assert result.action == "proceed"  # 2.0/2.5 = 80% > 60%


def test_aggregate_weak_consensus_defaults_to_flat():
    d1 = _make_decision(action="proceed", confidence=0.8, size_multiplier=1.5)
    d2 = _make_decision(action="flat", confidence=0.6, size_multiplier=0.5)
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "a"},
        {"decision": d2, "weight": 1.0, "name": "b"},
    ]
    result = aggregate_decisions(decisions)
    # 50/50 split -> defaults to flat (conservative)
    assert result.action == "flat"
    # Size multiplier capped at 0.7 for weak consensus
    assert result.size_multiplier <= 0.7


def test_aggregate_weak_consensus_no_flat_reduces_size():
    d1 = _make_decision(action="proceed", confidence=0.8, size_multiplier=1.5)
    d2 = _make_decision(action="flip", confidence=0.6, size_multiplier=0.5)
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "a"},
        {"decision": d2, "weight": 1.0, "name": "b"},
    ]
    result = aggregate_decisions(decisions)
    # 50/50 between proceed and flip, no flat -> proceed with reduced size
    assert result.action == "proceed"
    assert result.size_multiplier <= 0.7


def test_aggregate_regime_consensus():
    d1 = _make_decision(regime="trend")
    d2 = _make_decision(regime="trend")
    d3 = _make_decision(regime="range")
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "a"},
        {"decision": d2, "weight": 1.0, "name": "b"},
        {"decision": d3, "weight": 1.0, "name": "c"},
    ]
    result = aggregate_decisions(decisions)
    assert result.regime == "trend"  # 2 out of 3


def test_aggregate_combines_notes():
    d1 = _make_decision(notes="bullish setup")
    d2 = _make_decision(notes="risky entry")
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "conservative"},
        {"decision": d2, "weight": 1.0, "name": "aggressive"},
    ]
    result = aggregate_decisions(decisions)
    assert "[conservative]" in result.notes
    assert "[aggressive]" in result.notes
    assert "bullish setup" in result.notes
    assert "risky entry" in result.notes


def test_aggregate_combines_memory():
    d1 = _make_decision()
    d1.memory_update = "BTC showing strength"
    d2 = _make_decision()
    d2.memory_update = "ETH lagging"
    decisions = [
        {"decision": d1, "weight": 1.0, "name": "a"},
        {"decision": d2, "weight": 1.0, "name": "b"},
    ]
    result = aggregate_decisions(decisions)
    assert "BTC showing strength" in result.memory_update
    assert "ETH lagging" in result.memory_update


# ── Disagreement Metrics ────────────────────────────────────


def test_disagreement_metrics_single():
    d = _make_decision()
    result = get_disagreement_metrics([{"decision": d}])
    assert result["disagreement"] is False


def test_disagreement_metrics_agree():
    d1 = _make_decision(action="proceed", confidence=0.8, regime="trend")
    d2 = _make_decision(action="proceed", confidence=0.7, regime="trend")
    result = get_disagreement_metrics([
        {"decision": d1}, {"decision": d2},
    ])
    assert result["disagreement"] is False
    assert result["regime_agreement"] is True
    assert result["confidence_spread"] == 0.1


def test_disagreement_metrics_disagree():
    d1 = _make_decision(action="proceed", confidence=0.9, regime="trend")
    d2 = _make_decision(action="flat", confidence=0.3, regime="range")
    result = get_disagreement_metrics([
        {"decision": d1}, {"decision": d2},
    ])
    assert result["disagreement"] is True
    assert result["regime_agreement"] is False
    assert result["confidence_spread"] == 0.6
    assert result["num_providers"] == 2
