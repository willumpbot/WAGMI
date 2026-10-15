"""OWNER_PLAN_EXEC per-plan EXIT MODE.

profits_only (default): bot may bank partials (total <= 50% of original qty) but never moves the
owner's stop and never fully closes early. hands_off: no partials either. bot_manages: no limits.
Bot-opened positions must be completely unaffected.
"""
import json
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from execution.position_manager import PositionManager, Position  # noqa: E402
from llm.exit_types import ExitDecision  # noqa: E402

MODES = ("profits_only", "hands_off", "bot_manages")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "hivemind").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    for k in ("OWNER_PLAN_EXIT_MODE_DEFAULT", "OWNER_PLAN_EXIT_MODE_FORCE", "BREAKEVEN_RATCHET"):
        monkeypatch.delenv(k, raising=False)
    return data


def _pos(mode="__missing__", owner=True, side="LONG", qty=1.0, symbol="ETH"):
    er = {"owner_plan_id": "p1", "owner_trade": True} if owner else {}
    if owner and mode != "__missing__":
        er["exit_mode"] = mode
    if side == "LONG":
        p = Position(symbol=symbol, side="LONG", entry=3000.0, qty=qty, sl=2950.0, tp1=3050.0, tp2=3150.0,
                     strategy=ope.OWNER_STRATEGY if owner else "llm_first", entry_reasons=er)
    else:
        p = Position(symbol=symbol, side="SHORT", entry=3000.0, qty=qty, sl=3050.0, tp1=2950.0, tp2=2850.0,
                     strategy=ope.OWNER_STRATEGY if owner else "llm_first", entry_reasons=er)
    p._transition("OPEN")
    p.highest_price = p.lowest_price = 3000.0
    return p


def _pm_with(pos):
    pm = PositionManager()
    pm.positions[pos.symbol] = pos
    return pm


def _owner_log(sandbox):
    p = sandbox / "hivemind" / "owner_exit_decisions.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


# ── helper: owner_exit_mode ─────────────────────────────────────────────────

def test_mode_resolution_defaults_and_non_owner(sandbox):
    assert ope.owner_exit_mode(_pos(owner=False)) == "bot_manages"
    assert ope.owner_exit_mode(_pos()) == "profits_only"               # missing -> default
    assert ope.owner_exit_mode(_pos("garbage")) == "profits_only"      # invalid -> default
    for m in MODES:
        assert ope.owner_exit_mode(_pos(m)) == m
    assert ope.owner_exit_mode(_pos("Hands-Off")) == "hands_off"
    assert ope.owner_exit_mode(None) == "bot_manages"


def test_env_default_override(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_DEFAULT", "bot_manages")
    assert ope.owner_exit_mode(_pos()) == "bot_manages"                # missing -> env default
    assert ope.owner_exit_mode(_pos("hands_off")) == "hands_off"       # explicit wins over default
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_DEFAULT", "nonsense")
    assert ope.owner_exit_mode(_pos()) == "profits_only"
    # FORCE overrides every owner position, never touches bot positions
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_FORCE", "bot_manages")
    assert ope.owner_exit_mode(_pos("hands_off")) == "bot_manages"
    assert ope.owner_exit_mode(_pos(owner=False)) == "bot_manages"
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_FORCE", "hands_off")
    assert ope.owner_exit_mode(_pos(owner=False)) == "bot_manages"


def test_partial_allowance(sandbox):
    p = _pos("profits_only", qty=1.0)
    assert ope.owner_partial_allowance(p) == pytest.approx(0.5)
    p.qty = 0.7                                   # 30% already banked
    assert ope.owner_partial_allowance(p) == pytest.approx(0.2)
    p.qty = 0.5
    assert ope.owner_partial_allowance(p) == 0.0
    assert ope.owner_partial_allowance(_pos("hands_off")) == 0.0
    assert ope.owner_partial_allowance(_pos("bot_manages")) == pytest.approx(1.0)
    assert ope.owner_partial_allowance(_pos(owner=False)) == pytest.approx(1.0)


# ── exit engine gate ────────────────────────────────────────────────────────

def _engine(sandbox, monkeypatch):
    from llm import exit_engine as ee
    monkeypatch.setattr(ee, "_EXIT_LOG_FILE", str(sandbox / "exit_decisions.jsonl"))
    return ee.ExitEngine()


def _tighten():
    return ExitDecision(symbol="ETH", exit_action="tighten_sl", exit_confidence=0.8, new_sl=2990.0, reason="x")


def _close():
    return ExitDecision(symbol="ETH", exit_action="close", exit_confidence=0.95,
                        reason="thesis invalidated, regime shift")


def _partial(pct=0.5):
    return ExitDecision(symbol="ETH", exit_action="partial", exit_confidence=0.8, partial_pct=pct, reason="bank")


@pytest.mark.parametrize("mode,allowed", [("profits_only", False), ("hands_off", False), ("bot_manages", True)])
def test_engine_tighten_sl(sandbox, monkeypatch, mode, allowed):
    eng = _engine(sandbox, monkeypatch)
    pos = _pos(mode)
    res = eng.apply_exit_decision(_tighten(), pos, 3020.0)
    assert res["applied"] is allowed
    assert pos.sl == (2990.0 if allowed else 2950.0)
    rows = _owner_log(sandbox)
    assert rows and rows[-1]["exit_mode"] == mode and rows[-1]["applied"] is allowed


@pytest.mark.parametrize("mode,allowed", [("profits_only", False), ("hands_off", False), ("bot_manages", True)])
def test_engine_widen_tp(sandbox, monkeypatch, mode, allowed):
    eng = _engine(sandbox, monkeypatch)
    pos = _pos(mode)
    res = eng.apply_exit_decision(ExitDecision(symbol="ETH", exit_action="widen_tp", exit_confidence=0.8,
                                               new_tp=3300.0, reason="run"), pos, 3020.0)
    assert res["applied"] is allowed
    assert pos.tp2 == (3300.0 if allowed else 3150.0)


@pytest.mark.parametrize("mode,allowed", [("profits_only", False), ("hands_off", False), ("bot_manages", True)])
def test_engine_ai_close(sandbox, monkeypatch, mode, allowed):
    eng = _engine(sandbox, monkeypatch)
    res = eng.apply_exit_decision(_close(), _pos(mode), 3020.0)   # profitable + RQ9 reason -> bot allows
    assert res["applied"] is allowed
    assert res["action"] == ("close" if allowed else "safety_gated")
    if not allowed:
        assert "no early full close" in res["details"]


def test_engine_partial_profits_only_allowed_then_capped(sandbox, monkeypatch):
    eng = _engine(sandbox, monkeypatch)
    pos = _pos("profits_only", qty=1.0)
    d = _partial(0.8)                                    # asks for 80% -> clipped to the 50% cap
    res = eng.apply_exit_decision(d, pos, 3020.0)
    assert res["applied"] and res["action"] == "partial"
    assert res["partial_pct"] == pytest.approx(0.5)
    # book it like position_wiring does
    pm = _pm_with(pos)
    ev = pm.partial_close("ETH", res["partial_pct"], 3020.0, action="LLM_EXIT_PARTIAL")
    assert ev is not None and ev.qty == pytest.approx(0.5) and pos.qty == pytest.approx(0.5)
    assert pos.sl == 2950.0
    # cap now exhausted -> rejected
    res2 = eng.apply_exit_decision(_partial(0.2), pos, 3030.0)
    assert not res2["applied"] and "cap reached" in res2["details"]
    rows = _owner_log(sandbox)
    assert rows[-1]["applied"] is False and rows[-1]["exit_mode"] == "profits_only"


def test_engine_partial_hands_off_rejected_bot_manages_unclipped(sandbox, monkeypatch):
    eng = _engine(sandbox, monkeypatch)
    res = eng.apply_exit_decision(_partial(0.5), _pos("hands_off"), 3020.0)
    assert not res["applied"] and "hands_off" in res["details"]
    res = eng.apply_exit_decision(_partial(0.8), _pos("bot_manages"), 3020.0)
    assert res["applied"] and res["partial_pct"] == pytest.approx(0.8)


def test_engine_non_owner_unaffected(sandbox, monkeypatch):
    eng = _engine(sandbox, monkeypatch)
    pos = _pos(owner=False)
    assert eng.apply_exit_decision(_tighten(), pos, 3020.0)["applied"] and pos.sl == 2990.0
    assert eng.apply_exit_decision(_close(), _pos(owner=False), 3020.0)["applied"]
    r = eng.apply_exit_decision(_partial(0.8), _pos(owner=False), 3020.0)
    assert r["applied"] and r["partial_pct"] == pytest.approx(0.8)
    assert not _owner_log(sandbox), "bot positions never write the owner exit log"


# ── position manager: profit lock / ratchet / TP1 / trailing ────────────────

@pytest.mark.parametrize("mode", ["profits_only", "hands_off"])
def test_profit_lock_and_ratchet_skipped(sandbox, monkeypatch, mode):
    monkeypatch.setenv("BREAKEVEN_RATCHET", "true")
    pos = _pos(mode)
    pm = _pm_with(pos)
    for px in (3015.0, 3030.0, 3045.0):                   # 0.3R .. 0.9R: BE + lock triggers for a bot trade
        assert pm.update_price("ETH", px) == []
    assert pos.sl == 2950.0


def test_profit_lock_still_moves_bot_and_bot_manages(sandbox, monkeypatch):
    for p in (_pos(owner=False), _pos("bot_manages")):
        pm = _pm_with(p)
        pm.update_price("ETH", 3045.0)
        assert p.sl > 3000.0, "profit lock must still act on bot positions / bot_manages owner plans"


def test_tp1_partial_without_breakeven_profits_only(sandbox):
    pos = _pos("profits_only", qty=1.0)
    pm = _pm_with(pos)
    ev = pm.update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"]
    assert ev[0].qty == pytest.approx(0.5) and pos.qty == pytest.approx(0.5)
    assert pos.sl == 2950.0, "TP1 must not move the owner's stop to breakeven"
    assert ev[0].metadata["new_sl"] == 2950.0
    # trailing never moves it either
    assert pm.update_price("ETH", 3120.0) == []
    assert pos.sl == 2950.0
    # owner's stop ends it, labelled SL (not TRAILING_STOP)
    ev = pm.update_price("ETH", 2949.0)
    assert ev and ev[-1].action == "SL" and pos.state == "CLOSED"


def test_tp1_leg_respects_cap_after_ai_partial(sandbox):
    pos = _pos("profits_only", qty=1.0)
    pm = _pm_with(pos)
    pm.partial_close("ETH", 0.4, 3020.0, action="LLM_EXIT_PARTIAL")
    assert pos.qty == pytest.approx(0.6)
    ev = pm.update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"] and ev[0].qty == pytest.approx(0.1)
    assert pos.original_qty - pos.qty == pytest.approx(0.5)
    assert pos.sl == 2950.0


def test_tp1_skipped_when_cap_exhausted(sandbox):
    pos = _pos("profits_only", qty=1.0)
    pm = _pm_with(pos)
    pm.partial_close("ETH", 0.5, 3020.0, action="LLM_EXIT_PARTIAL")
    assert pm.update_price("ETH", 3051.0) == []
    assert pos.state == "OPEN" and pos.qty == pytest.approx(0.5) and pos.sl == 2950.0
    ev = pm.update_price("ETH", 3151.0)                    # owner's target ends it
    assert ev and ev[-1].action == "TP2" and pos.state == "CLOSED"


def test_hands_off_no_tp1_partial(sandbox):
    pos = _pos("hands_off", qty=1.0)
    pm = _pm_with(pos)
    assert pm.update_price("ETH", 3051.0) == []
    assert pos.state == "OPEN" and pos.qty == pytest.approx(1.0) and pos.sl == 2950.0
    assert pm.update_price("ETH", 3052.0) == []
    assert len([r for r in _owner_log(sandbox) if r["source"] == "tp1_partial"]) == 1, "logged once, not per tick"
    assert pm.partial_close("ETH", 0.5, 3052.0) is None
    ev = pm.update_price("ETH", 3151.0)
    assert ev and ev[-1].action == "TP2"


def test_short_owner_profits_only(sandbox):
    pos = _pos("profits_only", side="SHORT", qty=1.0)
    pm = _pm_with(pos)
    pm.update_price("ETH", 2970.0)
    ev = pm.update_price("ETH", 2949.0)
    assert [e.action for e in ev] == ["TP1"] and pos.sl == 3050.0
    pm.update_price("ETH", 2880.0)
    assert pos.sl == 3050.0


def test_bot_position_tp1_still_moves_to_breakeven(sandbox):
    pos = _pos(owner=False, qty=1.0)
    pm = _pm_with(pos)
    ev = pm.update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"]
    assert pos.sl > 2950.0


# ── hold limits ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["profits_only", "hands_off"])
def test_hold_limits_skip_owner(sandbox, mode):
    pos = _pos(mode)
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=200)
    pm = _pm_with(pos)
    assert pm.check_hold_limits("ETH", 3020.0, 48, "tighten_sl") is None
    assert pm.check_hold_limits("ETH", 3020.0, 48, "force_close") is None
    assert pos.state != "CLOSED" and pos.sl == 2950.0


@pytest.mark.parametrize("mode", ["profits_only", "hands_off"])
def test_owner_plan_own_max_hold_closes(sandbox, mode):
    pos = _pos(mode)
    pos.entry_reasons = dict(pos.entry_reasons or {}, plan_max_hold_h=48)
    pm = _pm_with(pos)
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=10)
    assert pm.check_hold_limits("ETH", 3020.0, 48, "tighten_sl") is None and pos.sl == 2950.0
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=49)
    ev = pm.check_hold_limits("ETH", 3020.0, 48, "tighten_sl")
    assert ev is not None and ev.action == "OWNER_PLAN_MAX_HOLD"


def test_hold_limits_still_close_bot_and_bot_manages(sandbox):
    for p in (_pos(owner=False), _pos("bot_manages")):
        p.open_time = datetime.now(timezone.utc) - timedelta(hours=200)
        pm = _pm_with(p)
        ev = pm.check_hold_limits("ETH", 3020.0, 48, "tighten_sl")
        assert ev is not None and ev.action == "HOLD_LIMIT"


# ── exit-agent force close in core/llm_integration ──────────────────────────

def _run_exit_agent(monkeypatch, pos):
    import llm.autonomy as autonomy
    import llm.agents.coordinator as coord
    monkeypatch.setattr(autonomy, "get_llm_mode", lambda: 5)
    monkeypatch.setattr(autonomy, "should_call_llm", lambda m: True)
    monkeypatch.setattr(coord, "is_multi_agent_enabled", lambda: True)
    monkeypatch.setattr(coord, "get_coordinator", lambda: types.SimpleNamespace(
        get_exit_intelligence=lambda p, m: {"action": "full_close", "urgency": "critical", "reason": "dead"}))
    monkeypatch.setenv("EXIT_AGENT_COOLDOWN_S", "0")
    monkeypatch.setenv("EXIT_FEE_GUARD", "off")
    from core.llm_integration import LLMIntegrationMixin
    oe = MagicMock()
    oe.close_position.return_value = types.SimpleNamespace(filled=True)
    fake = types.SimpleNamespace(pos_mgr=_pm_with(pos), order_executor=oe, _last_prices={"ETH": 2980.0},
                                 _tick_regime_cache={}, _pending_exit_events=[],
                                 _pending_exit_lock=threading.Lock())
    LLMIntegrationMixin._run_exit_agent_checks(fake, "t")
    return fake, oe


@pytest.mark.parametrize("mode", ["profits_only", "hands_off"])
def test_exit_agent_force_close_skips_owner(sandbox, monkeypatch, mode):
    pos = _pos(mode)
    fake, oe = _run_exit_agent(monkeypatch, pos)
    assert not oe.close_position.called
    assert pos.state != "CLOSED" and fake._pending_exit_events == []
    assert any(r["source"] == "exit_agent_force_close" for r in _owner_log(sandbox))


@pytest.mark.parametrize("owner", [True, False])
def test_exit_agent_force_close_still_works_for_bot_and_bot_manages(sandbox, monkeypatch, owner):
    pos = _pos("bot_manages") if owner else _pos(owner=False)
    fake, oe = _run_exit_agent(monkeypatch, pos)
    assert oe.close_position.called
    assert pos.state == "CLOSED" and len(fake._pending_exit_events) == 1


# ── multi_strategy_main guards + open row ───────────────────────────────────

def test_multi_strategy_main_guards_present():
    src = (BOT / "multi_strategy_main.py").read_text(encoding="utf-8")
    assert "_owner_locked_ms = _owner_plan_exec.owner_exit_restricted(open_pos[symbol])" in src
    assert "open_pos[symbol].leverage > 1.0 and not _owner_locked_ms" in src        # funding avoidance
    assert "if symbol in open_pos and not _owner_locked_ms:" in src                 # MFE exits/tighten
    assert "elif _liq_dist < 0.03 and _owner_locked_ms:" in src                     # liq-warning tighten


def _plan(pid, mode=None):
    import time
    r = {"kind": "plan", "id": pid, "ts": time.time(), "coin": "ETH", "side": "LONG", "entry": 3000.0,
         "stop": 2950.0, "target": 3150.0, "price_at_plan": 3000.0, "entry_type": "market",
         "entry_window_h": 24, "leverage": 3, "risk_usd": 20.0, "setup": "breakout"}
    if mode:
        r["exit_mode"] = mode
    return r


@pytest.mark.parametrize("mode,expect", [(None, "profits_only"), ("hands_off", "hands_off"),
                                         ("bot_manages", "bot_manages")])
def test_open_copies_exit_mode_and_records_it(sandbox, monkeypatch, mode, expect):
    from tests.test_owner_plan_exec import FakeBot
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    with open(sandbox / "hivemind" / "owner_plans.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(_plan("em1", mode)) + "\n")
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"ETH": 3000.0}))
    pos = pm.positions["ETH"]
    assert pos.entry_reasons["exit_mode"] == expect
    assert ope.owner_exit_mode(pos) == expect
    fills = [json.loads(l) for l in (sandbox / "hivemind" / "owner_fills.jsonl").read_text().splitlines()]
    assert fills[0]["kind"] == "open" and fills[0]["exit_mode"] == expect


def test_plans_create_stores_exit_mode(tmp_path, monkeypatch):
    sys.path.insert(0, str(BOT / "tools" / "hivemind"))
    import plans
    monkeypatch.setattr(plans, "HM", tmp_path)
    monkeypatch.setattr(plans, "PLANS", tmp_path / "owner_plans.jsonl")
    monkeypatch.setattr(plans, "_context", lambda coin: {})
    monkeypatch.setattr(plans, "OUT", tmp_path / "plans.json")
    base = {"coin": "ETH", "side": "LONG", "entry": 3000, "stop": 2950, "target": 3150}
    # distinct targets: an identical re-add of a live plan returns the existing one (duplicate guard)
    assert plans.create(dict(base))["exit_mode"] == "profits_only"
    assert plans.create(dict(base, target=3151, exit_mode="hands_off"))["exit_mode"] == "hands_off"
    assert plans.create(dict(base, target=3152, exit_mode="bot_manages"))["exit_mode"] == "bot_manages"
    assert plans.create(dict(base, target=3153, exit_mode="yolo"))["exit_mode"] == "profits_only"
    dup = plans.create(dict(base, exit_mode="hands_off"))
    assert dup.get("duplicate") and dup["exit_mode"] == "profits_only"


@pytest.mark.parametrize("flag,allowed", [("true", False), ("false", True)])
def test_profits_only_partial_at_a_loss(sandbox, monkeypatch, flag, allowed):
    monkeypatch.setenv("OWNER_PROFITS_ONLY_REQUIRE_PROFIT", flag)
    eng = _engine(sandbox, monkeypatch)
    res = eng.apply_exit_decision(_partial(0.3), _pos("profits_only"), 2980.0)    # LONG entry 3000 -> at a loss
    assert res["applied"] is allowed
    if not allowed:
        assert "only while in profit" in res["details"]


def test_profits_only_partial_in_profit_still_allowed_with_flag(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_PROFITS_ONLY_REQUIRE_PROFIT", "true")
    eng = _engine(sandbox, monkeypatch)
    assert eng.apply_exit_decision(_partial(0.3), _pos("profits_only"), 3020.0)["applied"]
    assert eng.apply_exit_decision(_partial(0.3), _pos("profits_only", side="SHORT"), 2980.0)["applied"]
    assert not eng.apply_exit_decision(_partial(0.3), _pos("profits_only", side="SHORT"), 3020.0)["applied"]


def test_require_profit_never_touches_bot_positions(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_PROFITS_ONLY_REQUIRE_PROFIT", "true")
    eng = _engine(sandbox, monkeypatch)
    assert eng.apply_exit_decision(_partial(0.3), _pos("bot_manages"), 2980.0)["applied"]


def test_owner_exit_row_records_price_and_profit_state(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_PROFITS_ONLY_REQUIRE_PROFIT", "false")
    eng = _engine(sandbox, monkeypatch)
    eng.apply_exit_decision(_partial(0.3), _pos("profits_only"), 2980.0)
    row = _owner_log(sandbox)[-1]
    assert row["current_price"] == 2980.0 and row["in_profit"] is False
    assert row["would_block_require_profit"] is True and row["unrealized_bps"] < 0
