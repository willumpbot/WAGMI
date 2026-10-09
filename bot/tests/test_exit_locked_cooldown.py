"""EXIT_AGENT_LOCKED_COOLDOWN_S: profit-locked positions skip repeat exit-agent LLM calls (default off)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from llm.agents.coordinator import AgentCoordinator


def _coord():
    c = AgentCoordinator.__new__(AgentCoordinator)
    c.configs = {}
    c._build_exit_input = MagicMock(return_value="{}")
    c._call_agent = MagicMock(return_value=SimpleNamespace(ok=False, data={}, error="x"))
    return c


LOCKED_SHORT = {"symbol": "NEAR", "side": "SHORT", "entry": 5.221, "sl": 4.639, "current_price": 4.55}
OPEN_LONG = {"symbol": "BTC", "side": "LONG", "entry": 80000, "sl": 78000, "current_price": 80500}


def test_profit_locked_detection():
    assert AgentCoordinator._exit_profit_locked(LOCKED_SHORT)
    assert AgentCoordinator._exit_profit_locked({"side": "LONG", "entry": 100, "sl": 101})
    assert not AgentCoordinator._exit_profit_locked(OPEN_LONG)
    assert not AgentCoordinator._exit_profit_locked({"side": "SHORT", "entry": 100, "sl": 0})


def test_off_by_default_calls_every_time(monkeypatch):
    monkeypatch.delenv("EXIT_AGENT_LOCKED_COOLDOWN_S", raising=False)
    c = _coord()
    for _ in range(3):
        c.get_exit_intelligence(dict(LOCKED_SHORT))
    assert c._call_agent.call_count == 3


def test_locked_position_throttled(monkeypatch):
    monkeypatch.setenv("EXIT_AGENT_LOCKED_COOLDOWN_S", "3600")
    c = _coord()
    for _ in range(4):
        c.get_exit_intelligence(dict(LOCKED_SHORT))
    assert c._call_agent.call_count == 1


def test_unlocked_position_never_throttled(monkeypatch):
    monkeypatch.setenv("EXIT_AGENT_LOCKED_COOLDOWN_S", "3600")
    c = _coord()
    for _ in range(3):
        c.get_exit_intelligence(dict(OPEN_LONG))
    assert c._call_agent.call_count == 3
