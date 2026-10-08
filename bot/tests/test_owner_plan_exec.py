"""OWNER_PLAN_EXEC: the bot paper-trades the owner's saved plans and manages the exit itself,
while owner trades NEVER feed the bot's books, stats or learning.

Exchange is the real paper OrderExecutor (no exchange object -> simulated fills), LLM is never called.
The close-isolation test runs the REAL per-event close loop extracted verbatim from
MultiStrategyBot._process_symbol against a bot whose every learning/accounting collaborator is a
tripwire, inside a temp data dir that is hash-snapshotted before/after.
"""
import ast
import hashlib
import json
import os
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from execution.order_executor import OrderExecutor  # noqa: E402
from execution import position_manager as pm_mod  # noqa: E402
from execution.position_manager import PositionManager, Position  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

class Tripwire(Exception):
    pass


def _trip(name):
    def f(*a, **k):
        raise Tripwire(f"owner close touched {name}")
    return f


class FakeBot:
    """Only the attributes the owner path is allowed to use; anything else is a tripwire."""

    def __init__(self, pos_mgr, prices):
        self.pos_mgr = pos_mgr
        self.order_executor = OrderExecutor(mode="paper")
        self._last_prices = prices
        self._shadow_close = None
        self._tick_regime_cache = {}
        self.ops_guard = types.SimpleNamespace(is_killed=False)
        self.telegram_bot = types.SimpleNamespace(is_paused=False)
        self.degradation = types.SimpleNamespace(should_halt_entries=lambda: False)
        self.fetcher = types.SimpleNamespace(fetch_multi_timeframe=lambda *a, **k: {})
        import threading
        self._executing_lock = threading.Lock()
        self._executing_symbols = set()

    def __getattr__(self, name):  # only called for MISSING attributes
        raise Tripwire(f"owner path touched bot.{name}")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """cwd + DATA_DIR + hivemind dir all inside tmp; OWNER_PLAN_EXEC on."""
    data = tmp_path / "data"
    (data / "hivemind").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    return data


def _plan(pid, coin="BTC", side="LONG", entry=60000.0, stop=59000.0, target=63000.0, etype="limit",
          price_at_plan=None, ts=None, risk_usd=20.0, window_h=24.0):
    return {"kind": "plan", "id": pid, "ts": time.time() if ts is None else ts, "coin": coin, "side": side,
            "entry": entry, "stop": stop, "target": target, "price_at_plan": price_at_plan or entry,
            "entry_type": etype, "entry_window_h": window_h, "max_hold_h": 48, "leverage": 3,
            "risk_usd": risk_usd, "setup": "breakout", "reason": "test"}


def _write_rows(data, *rows):
    with open(data / "hivemind" / "owner_plans.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _state(data):
    return json.loads((data / "hivemind" / "owner_orders_state.json").read_text(encoding="utf-8"))["plans"]


def _fills(data):
    p = data / "hivemind" / "owner_fills.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


# ── flag off ──────────────────────────────────────────────────────────────

def test_flag_off_is_default_and_tick_hook_is_gated(monkeypatch):
    monkeypatch.delenv("OWNER_PLAN_EXEC", raising=False)
    assert ope.enabled() is False
    src = (BOT / "multi_strategy_main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_tick_once")
    calls = [n for n in ast.walk(tick) if isinstance(n, ast.If)
             and "_owner_plan_exec.enabled()" in ast.get_source_segment(src, n.test)]
    assert len(calls) == 1, "drain must be called only under `if _owner_plan_exec.enabled():`"
    body = ast.get_source_segment(src, calls[0])
    assert "_drain_owner_orders" in body


def test_flag_off_drain_never_runs_and_bot_closes_untouched(sandbox, monkeypatch):
    monkeypatch.delenv("OWNER_PLAN_EXEC", raising=False)
    _write_rows(sandbox, _plan("p1", etype="market"))
    pm = PositionManager()
    bot = FakeBot(pm, {"BTC": 60000.0})
    # the gated hook, verbatim semantics
    if ope.enabled():
        ope.drain(bot)
    assert pm.get_open_count() == 0
    assert not (sandbox / "hivemind" / "owner_orders_state.json").exists()
    # A normal bot close is NOT diverted: it proceeds to equity booking (tripwired here).
    pos = Position(symbol="ETH", side="LONG", entry=3000.0, qty=0.1, sl=2900.0, tp1=3100.0, tp2=3200.0,
                   strategy="llm_first")
    pos._transition("OPEN")
    pm.positions["ETH"] = pos
    ev = pm.force_close("ETH", 3050.0, "SL")
    with pytest.raises(Tripwire, match="risk_mgr"):
        _run_close_loop(bot, "ETH", [ev])
    assert not _fills(sandbox)


# ── entries ───────────────────────────────────────────────────────────────

def test_limit_fills_only_on_cross(sandbox):
    _write_rows(sandbox, _plan("lim1", entry=60000.0, price_at_plan=60800.0))
    pm = PositionManager()
    bot = FakeBot(pm, {"BTC": 60500.0})
    ope.drain(bot)
    assert _state(sandbox)["lim1"]["status"] == "queued"
    assert pm.get_open_count() == 0
    bot._last_prices["BTC"] = 59950.0          # crossed down through 60000
    ope.drain(bot)
    st = _state(sandbox)["lim1"]
    assert st["status"] == "open"
    pos = pm.positions["BTC"]
    assert pos.strategy == ope.OWNER_STRATEGY
    assert pos.entry_reasons["owner_plan_id"] == "lim1"
    assert pos.sl == 59000.0 and pos.tp2 == 63000.0
    r = pos.entry - 59000.0
    assert abs(pos.tp1 - min(pos.entry + r, (pos.entry + 63000.0) / 2)) <= 1.0
    assert abs(pos.qty * r - 20.0) < 0.5      # qty = risk_usd / |entry - stop|
    assert pos.trade_profile.entry_type == "MEDIUM"
    assert pm.trade_log == []                 # owner OPEN never enters the bot's trade log
    assert [f["kind"] for f in _fills(sandbox)] == ["open"]


def test_limit_expires_unfilled(sandbox):
    _write_rows(sandbox, _plan("old", price_at_plan=60800.0, ts=time.time() - 30 * 3600, window_h=24))
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"BTC": 59000.0}))
    assert _state(sandbox)["old"]["status"] == "expired"
    assert pm.get_open_count() == 0


def test_market_stale_rule(sandbox):
    _write_rows(sandbox,
                _plan("m_far", coin="BTC", etype="market", entry=60000.0),
                _plan("m_ok", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0),
                _plan("m_old", coin="SOL", etype="market", entry=150.0, stop=147.0, target=160.0,
                      ts=time.time() - 3 * 3600))
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"BTC": 60400.0, "ETH": 3006.0, "SOL": 150.0}))   # BTC +0.67%, ETH +0.2%
    st = _state(sandbox)
    assert st["m_far"]["status"] == "stale" and "0.67%" in st["m_far"]["reason"]
    assert st["m_ok"]["status"] == "open"
    assert st["m_old"]["status"] == "stale"
    assert set(pm.get_open_positions()) == {"ETH"}


def test_non_default_symbol_rejected(sandbox):
    _write_rows(sandbox, _plan("doge", coin="DOGE", etype="market", entry=0.2, stop=0.19, target=0.23))
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"DOGE": 0.2}))
    st = _state(sandbox)["doge"]
    assert st["status"] == "rejected" and "DOGE" in st["reason"]
    assert pm.get_open_count() == 0


def test_duplicate_symbol_blocked_when_bot_holds_it(sandbox):
    pm = PositionManager()
    bot_pos = Position(symbol="ETH", side="SHORT", entry=3000.0, qty=0.1, sl=3100.0, tp1=2900.0, tp2=2800.0,
                       strategy="llm_first")
    bot_pos._transition("OPEN")
    pm.positions["ETH"] = bot_pos
    _write_rows(sandbox, _plan("dup", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0))
    ope.drain(FakeBot(pm, {"ETH": 3000.0}))
    st = _state(sandbox)["dup"]
    assert st["status"] == "blocked" and st["reason"] == "bot already in ETH"
    assert pm.positions["ETH"] is bot_pos and bot_pos.side == "SHORT"


def test_halts_keep_plan_pending(sandbox):
    _write_rows(sandbox, _plan("h", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0))
    pm = PositionManager()
    bot = FakeBot(pm, {"ETH": 3000.0})
    bot.ops_guard.is_killed = True
    ope.drain(bot)
    assert _state(sandbox)["h"]["status"] == "queued" and "kill" in _state(sandbox)["h"]["reason"]
    bot.ops_guard.is_killed = False
    ope.drain(bot)
    assert _state(sandbox)["h"]["status"] == "open"


def test_idempotent_across_restart(sandbox):
    _write_rows(sandbox,
                _plan("once", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0),
                _plan("wait", coin="BTC", entry=60000.0, price_at_plan=60800.0))
    pm = PositionManager()
    bot = FakeBot(pm, {"ETH": 3000.0, "BTC": 60500.0})
    ope.drain(bot)
    ope.drain(bot)
    assert [f["kind"] for f in _fills(sandbox)] == ["open"]
    # "restart": brand-new process objects, same files on disk
    pm2 = PositionManager()
    bot2 = FakeBot(pm2, {"ETH": 3000.0, "BTC": 60500.0})
    ope.drain(bot2)
    assert "ETH" not in pm2.positions, "a processed plan must never be re-opened after restart"
    assert _state(sandbox)["wait"]["status"] == "queued"
    bot2._last_prices["BTC"] = 59990.0          # the queued limit survives the restart and fills
    ope.drain(bot2)
    assert _state(sandbox)["wait"]["status"] == "open" and "BTC" in pm2.positions
    assert [f["kind"] for f in _fills(sandbox)] == ["open", "open"]


def test_cancel_before_fill(sandbox):
    _write_rows(sandbox, _plan("c1", entry=60000.0, price_at_plan=60800.0))
    pm = PositionManager()
    bot = FakeBot(pm, {"BTC": 60500.0})
    ope.drain(bot)
    _write_rows(sandbox, {"kind": "cancel", "id": "c1", "ts": time.time()})
    bot._last_prices["BTC"] = 59900.0
    ope.drain(bot)
    assert _state(sandbox)["c1"]["status"] == "cancelled"
    assert pm.get_open_count() == 0


def test_live_mode_executor_rejected(sandbox):
    _write_rows(sandbox, _plan("lv", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0))
    pm = PositionManager()
    bot = FakeBot(pm, {"ETH": 3000.0})
    bot.order_executor = types.SimpleNamespace(mode="live")
    ope.drain(bot)
    assert _state(sandbox)["lv"]["status"] == "rejected"
    assert pm.get_open_count() == 0


# ── the key one: closes never reach the bot's books ────────────────────────

def _close_loop_src():
    import multi_strategy_main as msm
    src = Path(msm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_symbol")
    loop = next(n for n in ast.walk(fn) if isinstance(n, ast.For)
                and isinstance(n.target, ast.Name) and n.target.id == "event"
                and isinstance(n.iter, ast.Name) and n.iter.id == "events")
    body = textwrap.dedent("    " * 0 + " " * loop.col_offset + ast.get_source_segment(src, loop))
    return msm, body


def _run_close_loop(bot, symbol, events):
    msm, body = _close_loop_src()
    code = "def _run(self, symbol, events, trace_id):\n" + textwrap.indent(body, "    ")
    ns = dict(vars(msm))
    for name in ("log_trade", "log_closed_trade", "record_trade_outcome", "update_signal_traded",
                 "format_trade_event_telegram"):
        ns[name] = _trip(name)
    exec(compile(code, "<close_loop>", "exec"), ns)
    ns["_run"](bot, symbol, events, "test")


def _snapshot(root: Path, allowed):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if any(rel.startswith(a) for a in allowed):
                continue
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_owner_close_tp1_and_final_never_touch_bot_books(sandbox, monkeypatch):
    # Seed the files the bot's books/learning live in.
    seeds = {
        "trades.csv": "timestamp,symbol,side,pnl\n2026-10-01,BTC,LONG,1.0\n",
        "trade_ledger.csv": "ts,symbol,net_pnl\n2026-10-01,BTC,1.0\n",
        "llm/decisions.jsonl": '{"d":1}\n',
        "llm/deep_memory/trade_dna.json": "{}",
        "kelly_weights.json": "{}", "ic_history.json": "{}", "strategy_weights.json": "{}",
        "risk_equity_state.json": '{"equity": 5000.0}', "momentum_state.json": "{}",
        "agent_performance.json": "{}", "logs/exit_closes.jsonl": "",
    }
    for rel, txt in seeds.items():
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")

    # Tripwires on everything the position manager could feed on close.
    monkeypatch.setattr(pm_mod, "_get_tel", lambda: types.SimpleNamespace(log=_trip("trade_events telemetry")))
    if hasattr(pm_mod, "get_mechanical_bot_instrumentation"):
        monkeypatch.setattr(pm_mod, "get_mechanical_bot_instrumentation", _trip("mechanical instrumentation"))
    import llm.neuroplasticity as neuro
    monkeypatch.setattr(neuro, "run_neuroplasticity_cycle", _trip("neuroplasticity"))
    import execution.momentum_tracker as mt
    monkeypatch.setattr(mt, "get_momentum_tracker", _trip("momentum tracker"))

    _write_rows(sandbox, _plan("k1", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0,
                               risk_usd=50.0))
    pm = PositionManager(is_live=True)
    pm._backup_dir = sandbox / "position_backups"
    bot = FakeBot(pm, {"ETH": 3000.0})
    ope.drain(bot)
    pos = pm.positions["ETH"]
    assert pos.strategy == ope.OWNER_STRATEGY

    allowed = ("hivemind/", "position_backups/", "position_journal.jsonl")
    before = _snapshot(sandbox, allowed)

    # TP1 partial
    ev_tp1 = pm.update_price("ETH", pos.tp1 + 0.5)
    assert [e.action for e in ev_tp1] == ["TP1"]
    _run_close_loop(bot, "ETH", ev_tp1)
    assert pm.positions["ETH"].state != "CLOSED"
    # final close (TP2)
    ev_fin = pm.update_price("ETH", 3151.0)
    assert ev_fin and ev_fin[-1].is_position_close
    _run_close_loop(bot, "ETH", ev_fin)

    after = _snapshot(sandbox, allowed)
    assert after == before, f"owner close changed bot files: {set(after.items()) ^ set(before.items())}"
    assert pm.trade_log == [], "owner legs must not enter pos_mgr.trade_log (daily summary / trade summary)"
    assert "ETH" not in pm._last_close_time, "owner close must not arm the bot's loss cooldown"

    fills = _fills(sandbox)
    assert [f["kind"] for f in fills] == ["open", "partial", "final"]
    part, fin = fills[1], fills[2]
    assert part["plan_id"] == fin["plan_id"] == "k1" and part["reason"] == "TP1" and fin["reason"] == "TP2"
    assert part["pnl"] > 0 and fin["total_pnl"] > 0 and fin["total_r"] > 1.0
    assert abs(fin["total_pnl"] - pos.realized_pnl) < 1e-6
    st = _state(sandbox)["k1"]
    assert st["status"] == "closed" and st["r"] == pytest.approx(fin["total_r"], abs=1e-3)
    assert len(st["fills"]) == 2


def test_exit_agent_owner_run_skips_learning(monkeypatch):
    from llm.agents import coordinator as coord_mod
    from llm.agents import performance_tracker as pt
    from llm.agents import learning_integration as li
    calls = {"pt": 0, "fb": 0}
    monkeypatch.setattr(pt, "get_performance_tracker",
                        lambda: types.SimpleNamespace(record_pipeline_run=lambda **k: calls.__setitem__("pt", calls["pt"] + 1)))
    monkeypatch.setattr(li, "process_exit_feedback", lambda *a, **k: calls.__setitem__("fb", calls["fb"] + 1))
    out = types.SimpleNamespace(ok=True, data={"action": "full_close", "urgency": "high", "reason": "x"})
    fake = types.SimpleNamespace(configs={}, _build_exit_input=lambda p, m: "{}",
                                 _call_agent=lambda *a, **k: out, last_exit_output=None)
    fn = coord_mod.AgentCoordinator.get_exit_intelligence if hasattr(coord_mod, "AgentCoordinator") else None
    if fn is None:
        fn = next(v.get_exit_intelligence for v in vars(coord_mod).values()
                  if isinstance(v, type) and hasattr(v, "get_exit_intelligence"))
    fn(fake, {"symbol": "ETH", "side": "LONG", "owner_trade": True})
    assert calls == {"pt": 0, "fb": 0}
    fn(fake, {"symbol": "ETH", "side": "LONG"})
    assert calls == {"pt": 1, "fb": 1}, "bot positions must still feed exit learning"


def test_exit_engine_owner_decisions_logged_beside_plan(sandbox, monkeypatch):
    from llm import exit_engine as ee
    from llm.exit_types import ExitDecision
    bot_log = sandbox / "exit_decisions.jsonl"
    monkeypatch.setattr(ee, "_EXIT_LOG_FILE", str(bot_log))
    eng = ee.ExitEngine() if hasattr(ee, "ExitEngine") else next(
        v() for v in vars(ee).values() if isinstance(v, type) and hasattr(v, "_log_decision"))
    pos = Position(symbol="ETH", side="LONG", entry=3000.0, qty=0.1, sl=2950.0, tp1=3050.0, tp2=3150.0,
                   strategy=ope.OWNER_STRATEGY, entry_reasons={"owner_plan_id": "z"})
    eng._log_decision(ExitDecision(symbol="ETH", exit_action="hold", exit_confidence=0.5, reason="r"), pos, True, "d")
    assert not bot_log.exists()
    row = json.loads((sandbox / "hivemind" / "owner_exit_decisions.jsonl").read_text().splitlines()[0])
    assert row["owner_plan_id"] == "z"


def test_rotation_ignores_owner_positions():
    src = (BOT / "core" / "position_wiring.py").read_text(encoding="utf-8")
    seg = src[src.index("def _evaluate_rotations"):src.index("def _execute_rotation")]
    assert '"owner_plan"' in seg and "continue" in seg


def test_api_server_filters_owner_positions():
    import importlib
    try:
        api = importlib.import_module("api_server")
    except Exception as e:  # fastapi missing in some envs
        pytest.skip(f"api_server not importable: {e}")
    st = {"positions": {"BTC": {"strategy": "llm_first"}, "ETH": {"strategy": "owner_plan"}}}
    assert set(api._bot_positions(st)) == {"BTC"}
    assert set(api._owner_positions(st)) == {"ETH"}


# ── plans.py: exec_result + by_exec ────────────────────────────────────────

def test_plans_merges_exec_result_and_by_exec(tmp_path, monkeypatch):
    sys.path.insert(0, str(BOT / "tools" / "hivemind"))
    import plans
    monkeypatch.setattr(plans, "EXEC_STATE", tmp_path / "owner_orders_state.json")
    monkeypatch.setattr(plans, "EXEC_FILLS", tmp_path / "owner_fills.jsonl")
    (tmp_path / "owner_orders_state.json").write_text(json.dumps({"plans": {
        "a": {"status": "closed", "reason": "closed by bot: TP2", "risk_usd": 50},
        "b": {"status": "open", "reason": "limit crossed", "risk_usd": 10},
        "c": {"status": "stale", "reason": "price moved"}}}))
    rows = [{"kind": "open", "plan_id": "a", "side": "LONG", "entry": 100, "qty": 5, "risk_usd": 50},
            {"kind": "partial", "plan_id": "a", "pnl": 20, "qty": 2.5, "r": 0.4},
            {"kind": "final", "plan_id": "a", "pnl": 25, "qty": 2.5, "total_pnl": 45, "total_r": 0.9},
            {"kind": "open", "plan_id": "b", "side": "SHORT", "entry": 50, "qty": 2, "risk_usd": 10}]
    (tmp_path / "owner_fills.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    ex = plans._exec_results({"b": 46.0})
    assert ex["a"]["status"] == "closed" and ex["a"]["r"] == 0.9 and len(ex["a"]["fills"]) == 2
    assert ex["b"]["status"] == "open" and ex["b"]["r"] == pytest.approx(0.8) and ex["b"]["live"]
    assert ex["c"]["status"] == "stale" and ex["c"]["r"] is None
    pl = [{"id": "a", "setup": "breakout", "side": "LONG", "result": {"r": 0.5}, "exec_result": ex["a"]},
          {"id": "c", "setup": "breakout", "side": "LONG", "result": {"r": -1.0}, "exec_result": ex["c"]}]
    st = plans._stats(pl)
    assert st["by_exec"] == {"n": 1, "plan_avg_r": 0.5, "bot_avg_r": 0.9, "plan_total_r": 0.5,
                             "bot_total_r": 0.9, "bot_better": 1}
