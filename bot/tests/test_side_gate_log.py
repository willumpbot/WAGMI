"""M22 side-gate decision log (core/side_gate_log.py) -- LOGGING ONLY.

Drives the real MultiStrategyBot._process_symbol_llm_first with a mocked bot,
mocked LLM coordinator and synthetic gate state, and checks:
  - one row per evaluation, with the expected keys
  - blocked vs opened (with position_id) vs llm_skip vs downstream abort
  - a failing writer never changes or breaks the decision
  - the trading decision is identical with SIDE_GATE_LOG on vs off
Every write goes to tmp_path via SIDE_GATE_LOG_PATH (never live data).
"""
import inspect
import json
import random
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

import multi_strategy_main as msm
from core import entry_selectivity as es
from core import side_gate_log as sgl
from feedback import live_edge
from llm.decision_types import EntryDecision

SYMBOL = "SOL"
ENTRY = 150.0


# ───────────────────────────── fixtures ──────────────────────────────────

@pytest.fixture
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "side_gate_decisions.jsonl"
    monkeypatch.setenv("SIDE_GATE_LOG_PATH", str(p))
    monkeypatch.setenv("SIDE_GATE_LOG", "true")
    return p


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Deterministic, explicit gate configuration (never the ambient .env).
    for k, v in {"ENTRY_SELECTIVITY": "true", "ENTRY_SELECTIVITY_NEGEV": "shadow",
                 "ENTRY_SELECTIVITY_STREAK": "false", "LONG_REGIME_VETO": "true",
                 "TREND_DIRECTION_GATE": "shadow", "BLOCKED_GO_PROBE": "false",
                 "EXPLORATION_MODE": "false", "ADAPTIVE_STOPS": "false",
                 "LLM_PROVENANCE_STAMP": "true"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LIVING_EDGE_MULT_CAP", raising=False)
    # Synthetic living-value state: solo bucket below breakeven, longs a drain.
    monkeypatch.setattr(es, "_ensure_fresh", lambda: None)
    monkeypatch.setitem(es._cache, "solo", {"active": True, "n": 32, "wr": 0.188,
                                            "breakeven_wr": 0.57, "reason": "solo_below_breakeven"})
    monkeypatch.setitem(es._cache, "streak", {"n_star": None, "reason": "no_negative_streak_cohort"})
    monkeypatch.setitem(es._cache, "long", {"drain": True, "n": 22, "wr": 0.09,
                                            "breakeven_wr": 0.4, "reason": "long_below_breakeven"})
    monkeypatch.setattr(live_edge, "_ensure_fresh", lambda: None)
    monkeypatch.setitem(live_edge._cache, "mult", {(SYMBOL, "SELL"): 1.5})
    monkeypatch.setitem(live_edge._cache, "meta", {(SYMBOL, "SELL"): {"n": 40, "avg_pnl": 12.0}})
    monkeypatch.setitem(live_edge._cache, "side_mult", {"BUY": 0.25, "SELL": 1.5})
    monkeypatch.setitem(live_edge._cache, "side_meta", {})
    # Side mult the live path applies (trading_config wrapper).
    import trading_config
    monkeypatch.setattr(trading_config, "get_symbol_side_risk_mult",
                        lambda s, side: 1.5 if str(side).upper() in ("SELL", "SHORT") else 0.25)
    # Isolate every external side effect of the open path.
    import core.signal_pipeline as sp
    monkeypatch.setattr(sp, "SafetyFilterChain",
                        lambda *a, **k: SimpleNamespace(
                            evaluate=lambda **kw: SimpleNamespace(approved=True, rejection_reason="")))
    import llm.agents.coordinator as coord
    monkeypatch.setattr(coord, "is_multi_agent_enabled", lambda: True)
    import llm.deep_memory as dm

    def _no_dm():
        raise RuntimeError("no deep memory in tests")
    monkeypatch.setattr(dm, "get_deep_memory", _no_dm)
    import execution.risk_cap as rc
    monkeypatch.setattr(rc, "apply_risk_cap", lambda qty, *a, **k: qty)
    monkeypatch.setattr(msm, "log_trade", MagicMock())
    monkeypatch.setattr(msm, "Telemetry", MagicMock())
    monkeypatch.setattr(msm, "round_qty", lambda s, q: round(q, 6))
    monkeypatch.setattr(msm, "get_min_qty", lambda s: 0.0)


def _decision(action="go"):
    return EntryDecision(action=action, leverage=2.0, risk_pct=0.005, position_qty=1.0,
                         regime="trend", thesis="test thesis", confidence=0.7,
                         pipeline_id="pipe-1")


def _bot(monkeypatch, *, side="SELL", num_agree=2, action="go"):
    import llm.agents.coordinator as coord
    coordinator = MagicMock()
    coordinator.get_entry_decision.side_effect = lambda **kw: _decision(action)
    monkeypatch.setattr(coord, "get_coordinator", lambda: coordinator)

    sl = ENTRY * (1.02 if side == "SELL" else 0.98)
    tp1 = ENTRY * (0.97 if side == "SELL" else 1.03)
    raw = SimpleNamespace(symbol=SYMBOL, side=side, confidence=70.0, entry=ENTRY, sl=sl,
                          tp1=tp1, tp2=tp1, atr=2.0, strategy="ensemble",
                          metadata={"num_agree": num_agree, "regime_1h": "range",
                                    "strategies_agree": ["a", "b"][:num_agree]},
                          risk_reward_tp1=1.5, risk_reward_tp2=1.5, stop_width_pct=0.02)
    bot = MagicMock()
    bot.ensemble.evaluate_raw.return_value = raw
    bot.risk_mgr.equity = 5000.0
    bot.risk_mgr.daily_pnl = 0.0
    bot.risk_mgr.circuit_breaker_proximity = 1.0
    bot.risk_mgr.circuit_breaker.consecutive_losses = 0
    bot.risk_mgr.circuit_breaker.tripped = False
    bot._last_funding_rates = {}
    bot._last_prices = {}
    bot._price_changes_1h = {}
    bot._mech_opinion = {}
    bot._reflection_engine = None
    bot.counterfactual = None
    bot.execution_analytics = None
    bot.config.max_leverage = 25.0
    bot.config.max_portfolio_leverage = 5.0
    bot.pos_mgr.check_portfolio_notional_cap.return_value = True
    bot.pos_mgr.get_open_positions.return_value = {}
    bot.pos_mgr.open_position.return_value = SimpleNamespace(position_id="pid-123")
    bot.ops_guard.can_execute.return_value = {"allowed": True, "reason": ""}
    bot.ops_guard.check_duplicate_position.return_value = {"allowed": True}
    bot.fetcher.fetch_live_price.return_value = ENTRY
    bot.order_executor.open_position.return_value = SimpleNamespace(
        filled=True, fill_price=ENTRY, fill_qty=0.0, error=None)
    return bot


def _data():
    closes = [ENTRY * (1 + 0.001 * i) for i in range(30)]  # +~3% over 24h
    return {"1h": pd.DataFrame({"close": closes})}


def _run(bot):
    """Mirror the dispatcher: scope -> _process_symbol_llm_first -> end_scope."""
    random.seed(7)
    sgl.start_scope()
    err = None
    try:
        msm.MultiStrategyBot._process_symbol_llm_first(
            bot, SYMBOL, None, None, _data(), {}, ENTRY, "trace-1")
    except Exception as e:  # pragma: no cover - would be a test failure below
        err = e
        raise
    finally:
        sgl.end_scope(err)


def _rows(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _decision_fingerprint(bot):
    """Everything the bot DID: orders, positions, outcome tracking, counterfactuals."""
    return repr((bot.order_executor.open_position.call_args_list,
                 bot.pos_mgr.open_position.call_args_list,
                 bot._track_llm_first_outcome.call_args_list))


# ───────────────────────────── tests ─────────────────────────────────────

EXPECTED_KEYS = {"schema", "ts", "ts_utc", "trace_id", "pipeline_id", "symbol", "side",
                 "llm_action", "llm_confidence", "stage", "selectivity", "gate", "probe",
                 "side_mult", "outcome", "position_id", "exploration"}


def test_opened_row_has_keys_side_mult_and_position_id(monkeypatch, log_path):
    bot = _bot(monkeypatch, side="SELL", num_agree=2)
    _run(bot)
    assert bot.pos_mgr.open_position.called
    rows = _rows(log_path)
    assert len(rows) == 1
    r = rows[0]
    assert EXPECTED_KEYS <= set(r)
    assert r["outcome"] == "opened" and r["position_id"] == "pid-123"
    assert r["trace_id"] == "trace-1" and r["pipeline_id"] == "pipe-1"
    assert r["gate"]["mode"] == "true" and r["gate"]["block"] is False
    legs = r["selectivity"]["legs"]
    assert legs["solo"]["verdict"] == "pass" and legs["solo"]["state"]["n"] == 32
    # +3% 24h on a short = no downside tailwind -> trend leg shadow-blocks only
    assert legs["trend_direction"]["would_fire"] is True
    assert legs["trend_direction"]["verdict"] == "shadow_block"
    assert legs["long_regime_veto"]["verdict"] == "pass"
    sm = r["side_mult"]
    assert sm["raw"] == 1.5 and sm["applied"] == 1.5
    assert sm["qty_post"] == pytest.approx(sm["qty_pre"] * 1.5)
    assert sm["evidence"]["source"] == "cell" and sm["evidence"]["cell"]["n"] == 40


def test_blocked_row(monkeypatch, log_path):
    bot = _bot(monkeypatch, side="BUY", num_agree=1)
    _run(bot)
    assert not bot.order_executor.open_position.called
    rows = _rows(log_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["outcome"] == "blocked" and r["position_id"] is None
    assert r["gate"]["block"] is True
    legs = r["selectivity"]["legs"]
    assert legs["solo"]["verdict"] == "block"
    assert legs["long_regime_veto"]["verdict"] == "block"
    assert legs["long_regime_veto"]["state"]["drain"] is True
    assert r["side_mult"] is None  # never reached sizing


def test_probe_fire_recorded(monkeypatch, log_path):
    monkeypatch.setenv("BLOCKED_GO_PROBE", "true")
    monkeypatch.setenv("BLOCKED_GO_PROBE_RATE", "0.5")
    monkeypatch.setattr(random, "random", lambda: 0.01)
    bot = _bot(monkeypatch, side="BUY", num_agree=1)
    _run(bot)
    r = _rows(log_path)[0]
    assert r["probe"]["fire"] is True and r["exploration"] is True
    assert r["outcome"] == "probe_opened" and r["position_id"] == "pid-123"


D24_EXPECTED = (ENTRY * 1.029 - ENTRY * 1.005) / (ENTRY * 1.005) * 100.0  # closes[-1] vs closes[-25]


def test_llm_skip_row(monkeypatch, log_path):
    bot = _bot(monkeypatch, side="SELL", action="skip")
    bot.risk_mgr.circuit_breaker.consecutive_losses = 4
    _run(bot)
    rows = _rows(log_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["outcome"] == "llm_skip"
    # laptop 171: skip rows carry the REAL inputs, not blanks
    assert r["gate"]["mode"] == "not_evaluated"
    legs = r["selectivity"]["legs"]
    assert legs["loss_streak"]["loss_streak"] == 4
    assert legs["trend_direction"]["sym_d24h"] == pytest.approx(D24_EXPECTED)
    assert legs["trend_direction"]["would_fire"] is True
    assert legs["trend_direction"]["input_missing"] is None


def test_missing_input_is_null_with_reason_not_false(monkeypatch, log_path):
    """A genuinely unavailable input -> would_fire None + input_missing, never False."""
    monkeypatch.setenv("ENTRY_SELECTIVITY", "off")
    monkeypatch.setitem(es._cache, "streak", {"n_star": 3})
    bot = _bot(monkeypatch, side="SELL", num_agree=2, action="skip")
    bot.risk_mgr.circuit_breaker = None   # streak unavailable -> int(0) per live formula
    random.seed(7)
    sgl.start_scope()
    try:
        msm.MultiStrategyBot._process_symbol_llm_first(
            bot, SYMBOL, None, None, {}, {}, ENTRY, "trace-1")   # no 1h data -> no d24h
    finally:
        sgl.end_scope()
    legs = _rows(log_path)[0]["selectivity"]["legs"]
    assert legs["trend_direction"]["sym_d24h"] is None
    assert legs["trend_direction"]["would_fire"] is None
    assert legs["trend_direction"]["input_missing"] == "sym_d24h"
    assert legs["neg_ev"]["would_fire"] is None
    assert legs["neg_ev"]["input_missing"] == "ev_per_dollar"
    # live path: missing breaker -> consecutive_losses defaults to 0 (a real value)
    assert legs["loss_streak"]["loss_streak"] == 0
    assert legs["loss_streak"]["would_fire"] is False


def test_gate_snapshot_null_when_input_missing():
    snap = es.gate_snapshot(num_agree=None, ev_per_dollar=None, loss_streak=None,
                            is_exploration=False, side="SELL", regime="range", sym_d24h=None)
    legs = snap["legs"]
    assert legs["solo"]["would_fire"] is None and legs["solo"]["input_missing"] == "num_agree"
    assert legs["trend_direction"]["would_fire"] is None
    # loss-streak: n_star None in fixture -> leg cannot fire, False is a real answer
    assert legs["loss_streak"]["would_fire"] is False and legs["loss_streak"]["input_missing"] is None


def test_downstream_abort_row(monkeypatch, log_path):
    bot = _bot(monkeypatch, side="SELL", num_agree=2)
    bot.order_executor.open_position.return_value = SimpleNamespace(
        filled=False, fill_price=0.0, fill_qty=0.0, error="rejected")
    _run(bot)
    r = _rows(log_path)[0]
    assert r["outcome"] == "not_opened" and r["abort_stage"] == "execution"


def test_gate_off_still_snapshots_state(monkeypatch, log_path):
    monkeypatch.setenv("ENTRY_SELECTIVITY", "off")
    bot = _bot(monkeypatch, side="BUY", num_agree=1)
    _run(bot)
    r = _rows(log_path)[0]
    assert r["outcome"] == "opened"
    assert r["gate"]["mode"] == "not_evaluated"
    legs = r["selectivity"]["legs"]
    # frozen solo gate WOULD fire, but the gate is off -> verdict off
    assert legs["solo"]["would_fire"] is True and legs["solo"]["verdict"] == "off"
    # laptop 171: real inputs, same formulas as the evaluated path (not blanks)
    assert legs["loss_streak"]["loss_streak"] == 0
    assert legs["trend_direction"]["sym_d24h"] == pytest.approx(D24_EXPECTED)
    assert legs["trend_direction"]["input_missing"] is None
    assert legs["long_regime_veto"]["would_fire"] is True


def test_gate_off_short_trend_would_fire_from_real_d24h(monkeypatch, log_path):
    monkeypatch.setenv("ENTRY_SELECTIVITY", "off")
    bot = _bot(monkeypatch, side="SELL", num_agree=2)
    _run(bot)
    legs = _rows(log_path)[0]["selectivity"]["legs"]
    assert legs["trend_direction"]["would_fire"] is True      # +2.4% 24h on a short
    assert legs["trend_direction"]["verdict"] == "off"


@pytest.mark.parametrize("side,num_agree", [("SELL", 2), ("BUY", 1), ("BUY", 2)])
def test_decisions_identical_logging_on_vs_off(monkeypatch, tmp_path, side, num_agree):
    fps = {}
    for flag in ("true", "false"):
        monkeypatch.setenv("SIDE_GATE_LOG", flag)
        monkeypatch.setenv("SIDE_GATE_LOG_PATH", str(tmp_path / f"log_{flag}.jsonl"))
        bot = _bot(monkeypatch, side=side, num_agree=num_agree)
        _run(bot)
        fps[flag] = _decision_fingerprint(bot)
    assert fps["true"] == fps["false"]
    assert len(_rows(tmp_path / "log_true.jsonl")) == 1
    assert _rows(tmp_path / "log_false.jsonl") == []


@pytest.mark.parametrize("side,num_agree", [("SELL", 2), ("BUY", 1)])
def test_writer_failure_does_not_affect_decision(monkeypatch, tmp_path, side, num_agree):
    monkeypatch.setenv("SIDE_GATE_LOG_PATH", str(tmp_path / "ok.jsonl"))
    good = _bot(monkeypatch, side=side, num_agree=num_agree)
    _run(good)

    def _boom(row):
        raise OSError("disk full")
    monkeypatch.setattr(sgl, "_append", _boom)

    def _boom_snap(**kw):
        raise RuntimeError("snapshot broke")
    monkeypatch.setattr(es, "gate_snapshot", _boom_snap)
    monkeypatch.setattr(live_edge, "side_mult_snapshot", lambda *a: 1 / 0)
    bad = _bot(monkeypatch, side=side, num_agree=num_agree)
    _run(bad)  # must not raise
    assert _decision_fingerprint(good) == _decision_fingerprint(bad)


def test_default_path_never_written_under_pytest(monkeypatch):
    monkeypatch.delenv("SIDE_GATE_LOG_PATH", raising=False)
    assert sgl._append({"x": 1}) is False


def test_gate_snapshot_matches_evaluate_entry():
    """Snapshot verdicts agree with the live gate's block decision."""
    for side, na, d24 in [("BUY", 1, 1.0), ("SELL", 2, -5.0), ("SELL", 1, 2.0), ("BUY", 3, None)]:
        block, reasons, mode = es.evaluate_entry(
            num_agree=na, ev_per_dollar=None, loss_streak=0, is_exploration=False,
            side=side, regime="range", sym_d24h=d24)
        snap = es.gate_snapshot(num_agree=na, ev_per_dollar=None, loss_streak=0,
                                is_exploration=False, side=side, regime="range", sym_d24h=d24)
        snap_block = any(l["verdict"] == "block" for l in snap["legs"].values())
        assert snap_block == block, (side, na, d24, reasons, snap)
    ex = es.gate_snapshot(num_agree=1, ev_per_dollar=None, loss_streak=0,
                          is_exploration=True, side="BUY", regime="range")
    assert ex["legs"]["solo"]["verdict"] == "exempt"


def test_dispatcher_wires_scope():
    src = inspect.getsource(msm.MultiStrategyBot._process_symbol)
    assert "_side_gate_log.start_scope()" in src
    assert "_side_gate_log.end_scope(_sgl_err)" in src


def test_laptop_sync_exports_log():
    from tools.hivemind import laptop_sync
    assert laptop_sync.APPENDS["side_gate_decisions"].name == "side_gate_decisions.jsonl"
