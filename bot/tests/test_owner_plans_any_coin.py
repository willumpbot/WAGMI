"""OWNER_PLAN_ANY_COIN: owner plans on ANY Hyperliquid perp get the same paper machinery as the bot's own 6.

Hyperliquid's info API is mocked (oac._post); the paper OrderExecutor, PositionManager, owner_plan_exec.drain,
record_owner_close, auto_recovery save/load and the bot's real _check_position_aging are the real code.
"""
import ast
import json
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from core import owner_any_coin as oac  # noqa: E402
from execution.position_manager import PositionManager  # noqa: E402
from tests.test_owner_plan_exec import FakeBot, Tripwire, _plan, _write_rows, _state, _fills  # noqa: E402

ATR_D = 0.08   # daily atr_at_fill for SUI


class HL:
    """Mocked Hyperliquid info API: allMids / metaAndAssetCtxs / candleSnapshot. Counts calls."""

    def __init__(self):
        self.mids = {"BTC": "60000", "ETH": "3000", "SUI": "3.05", "kPEPE": "0.012340", "@107": "1.0"}
        self.universe = [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
                         {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                         {"name": "SUI", "szDecimals": 1, "maxLeverage": 10},
                         {"name": "kPEPE", "szDecimals": 0, "maxLeverage": 10},
                         {"name": "OLDCOIN", "szDecimals": 0, "maxLeverage": 3, "isDelisted": True}]
        self.funding = {"SUI": "0.0000125", "kPEPE": "0.00001"}
        self.calls = []
        self.down = False

    def __call__(self, body, timeout=5.0):
        self.calls.append(body["type"])
        if self.down:
            raise OSError("HL down")
        if body["type"] == "allMids":
            return dict(self.mids)
        if body["type"] == "metaAndAssetCtxs":
            return [{"universe": self.universe},
                    [{"funding": self.funding.get(u["name"], "0")} for u in self.universe]]
        if body["type"] == "candleSnapshot":
            t0 = body["req"]["endTime"] - 30 * 3600 * 1000
            return [{"t": t0 + i * 3600 * 1000, "o": "3", "h": "3.05", "l": "2.97", "c": "3.0"} for i in range(30)]
        raise AssertionError(body)


class AnyBot(FakeBot):
    """FakeBot (every attribute outside the owner path is a tripwire) + what the any-coin manager reads."""

    def __init__(self, pos_mgr, prices, equity=5000.0):
        super().__init__(pos_mgr, prices)
        self.risk_mgr = types.SimpleNamespace(equity=equity, update_equity=_tw("risk_mgr.update_equity"),
                                              circuit_breaker=_tw("circuit_breaker"))
        self._pending_exit_events = []
        self._pending_exit_lock = threading.Lock()
        self._last_funding_rates = {}


def _tw(name):
    def f(*a, **k):
        raise Tripwire(f"owner any-coin touched {name}")
    return f


@pytest.fixture
def hl(monkeypatch):
    h = HL()
    oac._reset_for_tests()
    monkeypatch.setattr(oac, "_post", h)
    monkeypatch.setattr(oac, "MIDS_TTL_S", 0.0)
    yield h
    oac._reset_for_tests()


@pytest.fixture
def sandbox(tmp_path, monkeypatch, hl):
    data = tmp_path / "data"
    (data / "hivemind").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    for k in ("OWNER_PLAN_ANY_COIN", "OWNER_PLAN_EXIT_MODE_DEFAULT", "OWNER_PLAN_EXIT_MODE_FORCE", "OWNER_RUNNER_STYLE",
              "RISK_CAP_HARD_CLAMP", "MAX_RISK_PCT_CEILING", "SL_FILL_FIDELITY_FIX", "BREAKEVEN_RATCHET"):
        monkeypatch.delenv(k, raising=False)
    return data


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("OWNER_PLAN_ANY_COIN", "true")


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Route every save_position_state (runner saves, close saves) to a temp file."""
    import execution.auto_recovery as ar
    real = ar.save_position_state
    path = tmp_path / "position_state.json"
    monkeypatch.setattr(ar, "save_position_state", lambda pm, filepath=None: real(pm, str(path)))
    return path


def _sui(pid="s1", etype="limit", **kw):
    kw.setdefault("entry", 3.0)
    kw.setdefault("stop", 2.9)
    kw.setdefault("target", 3.5)
    kw.setdefault("price_at_plan", 3.1)
    return _plan(pid, coin="SUI", etype=etype, **kw)


def _tick(bot, hl, px=None, **mids):
    """One bot tick for the owner path: drain (flag-gated, as in _tick_once) then the any-coin manager."""
    if px is not None:
        hl.mids["SUI"] = str(px)
    for k, v in mids.items():
        hl.mids[k] = str(v)
    if ope.enabled():
        ope.drain(bot)
    return oac.manage(bot, "t")


# ── flag off: today's behaviour exactly ─────────────────────────────────────

def test_flag_off_rejection_unchanged_and_no_network(sandbox, hl):
    assert oac.enabled() is False
    _write_rows(sandbox, _plan("doge", coin="DOGE", etype="market", entry=0.2, stop=0.19, target=0.23),
                _sui("sui", etype="market", entry=3.05, price_at_plan=3.05))
    pm = PositionManager()
    bot = AnyBot(pm, {"DOGE": 0.2, "SUI": 3.05})
    _tick(bot, hl)
    st = _state(sandbox)
    for pid, c in (("doge", "DOGE"), ("sui", "SUI")):
        assert st[pid]["status"] == "rejected"
        assert st[pid]["reason"].startswith("bot only manages ") and st[pid]["reason"].endswith(f"; {c} is not one")
    assert pm.get_open_count() == 0 and hl.calls == [], "flag off must never touch the HL API"


def test_tick_hook_wired_and_scan_untouched():
    src = (BOT / "multi_strategy_main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    tick = ast.get_source_segment(src, fns["_tick_once"])
    assert "_owner_any_coin.manage(self, trace_id)" in tick
    assert tick.index("_drain_owner_orders(trace_id)") < tick.index("_owner_any_coin.manage(self, trace_id)")
    # the bot's own scan never sees these coins: the symbol loop is DEFAULT_SYMBOLS and nothing in the entry
    # path consults the any-coin registry
    assert "eval_order = self._prioritize_symbols(DEFAULT_SYMBOLS)" in tick
    for name in ("_process_symbol", "_process_symbol_llm_first"):
        assert "owner_any_coin" not in ast.get_source_segment(src, fns[name])


# ── flag on: a non-core coin runs the full owner machinery ──────────────────

def test_sui_limit_queues_then_fills_on_touch(sandbox, hl, on):
    _write_rows(sandbox, _sui())
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, 3.05)
    assert _state(sandbox)["s1"]["status"] == "queued" and pm.get_open_count() == 0
    _tick(bot, hl, 2.995)                                  # crossed down through 3.0
    st = _state(sandbox)["s1"]
    assert st["status"] == "open", st
    pos = pm.positions["SUI"]
    assert pos.strategy == ope.OWNER_STRATEGY and pos.entry_reasons["any_coin"] is True
    assert pos.entry_reasons["hl_coin"] == "SUI"
    assert pos.sl == 2.9 and pos.tp2 == 3.5
    assert abs(pos.qty * (pos.entry - 2.9) - 20.0) < 0.5   # risk_usd / R, same formula as a core plan
    assert pos.atr > 0                                     # 1h ATR from HL candles (bot fetcher has no SUI feed)
    assert [f["kind"] for f in _fills(sandbox)] == ["open"]
    assert bot._last_prices["SUI"] == 2.995               # manage() fed the mark
    from trading_config import DEFAULT_SYMBOLS
    assert "SUI" not in DEFAULT_SYMBOLS, "registration must never add the coin to the bot's own universe"
    assert set(hl.calls) <= {"allMids", "metaAndAssetCtxs", "candleSnapshot"}
    assert hl.calls.count("metaAndAssetCtxs") == 1         # metadata cached


def test_one_allmids_per_tick_for_all_extra_coins(sandbox, hl, on):
    _write_rows(sandbox, _sui("a", etype="market", entry=3.05, price_at_plan=3.05),
                _plan("b", coin="kPEPE", etype="market", entry=0.01234, stop=0.0120, target=0.0130, price_at_plan=0.01234))
    pm = PositionManager()
    bot = AnyBot(pm, {})
    oac.MIDS_TTL_S = 5.0                                    # production cache: drain + manage share one call
    _tick(bot, hl)
    assert set(pm.get_open_positions()) == {"SUI", "KPEPE"}
    assert hl.calls.count("allMids") == 1


def test_runner_half_trail_persist_restart_then_stop(sandbox, hl, on, monkeypatch, state_file):
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "true")
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (ATR_D, "test"))
    _write_rows(sandbox, _sui())
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, 3.05)
    _tick(bot, hl, 2.995)
    pos = pm.positions["SUI"]
    assert pos.entry_reasons["exit_style"] == "runner" and pos.entry_reasons["atr_at_fill"] == ATR_D
    orig, entry = pos.qty, pos.entry
    one_r = entry + (entry - 2.9)
    _tick(bot, hl, round(one_r + 0.005, 4))                  # +1R -> half
    rows = _fills(sandbox)
    assert [r["kind"] for r in rows] == ["open", "partial"]
    assert rows[1]["reason"] == "OWNER_RUNNER_HALF" and rows[1]["managed_by"] == "runner_half"
    assert rows[1]["coin"] == "SUI" and rows[1]["qty"] == pytest.approx(round(orig / 2 - 0.05, 1), abs=0.11)
    _tick(bot, hl, 3.30)                                    # trail -> 3.30 - 0.08
    assert pos.sl == pytest.approx(3.22)
    saved = json.loads(state_file.read_text())["positions"]["SUI"]
    assert saved["sl"] == pytest.approx(3.22) and saved["entry_reasons"]["owner_runner"]["half_taken"]

    # ---- restart: fresh process objects + empty any-coin registry, state restored from disk ----
    from execution.auto_recovery import load_position_state
    oac._reset_for_tests()
    monkeypatch.setattr(oac, "_post", hl)
    pm2 = PositionManager()
    assert load_position_state(pm2, str(state_file)) == 1
    bot2 = AnyBot(pm2, {})
    _tick(bot2, hl, 3.25)                                   # re-registered from metadata, no ratchet
    back = pm2.positions["SUI"]
    assert oac.is_extra("SUI") and back.sl == pytest.approx(3.22) and back.qty == pytest.approx(pos.qty)
    _tick(bot2, hl, 3.40)                                   # ratchet survives the restart
    assert back.sl == pytest.approx(3.32)
    _tick(bot2, hl, 3.31)                                   # through the trail -> remainder closes
    rows = _fills(sandbox)
    assert [r["kind"] for r in rows] == ["open", "partial", "final"]
    fin = rows[-1]
    assert fin["managed_by"] in ("runner_trail", "stop") and fin["exit_style"] == "runner"
    assert rows[1]["qty"] + fin["qty"] == pytest.approx(orig)
    assert fin["total_pnl"] == pytest.approx(rows[1]["pnl"] + fin["pnl"], abs=1e-6)
    assert fin["total_r"] > 0
    assert _state(sandbox)["s1"]["status"] == "closed"
    assert "SUI" not in pm2.positions and "SUI" not in bot2._last_prices   # cleaned like a core close


def test_stop_close_books_owner_row_never_bot_books(sandbox, hl, on):
    _write_rows(sandbox, _sui("st", etype="market", entry=3.05, price_at_plan=3.05, stop=2.95, target=3.4))
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, 3.05)
    assert pm.positions["SUI"].entry_reasons["exit_mode"] == "profits_only"
    _tick(bot, hl, 2.94)                                    # through the owner's stop (risk_mgr is a tripwire)
    rows = _fills(sandbox)
    assert [r["kind"] for r in rows] == ["open", "final"]
    assert rows[1]["reason"] == "SL" and rows[1]["managed_by"] == "stop" and rows[1]["total_r"] == pytest.approx(-1, abs=0.15)
    assert pm.trade_log == [] and "SUI" not in pm.positions
    assert pm.get_total_unrealized_pnl({"SUI": 2.0}) == 0.0


def test_time_limit_via_real_aging_check(sandbox, hl, on):
    from core.position_wiring import PositionWiringMixin
    p = _plan("tl", coin="kPEPE", etype="market", entry=0.01234, stop=0.0120, target=0.0130, price_at_plan=0.01234)
    _write_rows(sandbox, p)
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl)
    pos = pm.positions["KPEPE"]                              # bot symbol upper-cased, HL name kept for the API
    assert pos.entry_reasons["hl_coin"] == "kPEPE" and pos.entry == pytest.approx(0.012341, abs=2e-6)
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=49)
    bot.config = types.SimpleNamespace(max_hold_hours=72, hold_limit_action="tighten_sl")
    bot.alerts = None
    PositionWiringMixin._check_position_aging(bot)          # the bot's real 10-tick check queues the close
    assert [e.action for e in bot._pending_exit_events] == ["OWNER_PLAN_MAX_HOLD"]
    _tick(bot, hl)                                          # ... and the any-coin manager books it
    rows = _fills(sandbox)
    assert [r["kind"] for r in rows] == ["open", "final"]
    assert rows[1]["reason"] == "OWNER_PLAN_MAX_HOLD" and rows[1]["managed_by"] == "time"
    assert bot._pending_exit_events == [] and "KPEPE" not in pm.positions


def test_bot_manages_degrades_to_profits_only(sandbox, hl, on, monkeypatch):
    p = _sui("bm", etype="market", entry=3.05, price_at_plan=3.05)
    p["exit_mode"] = "bot_manages"
    _write_rows(sandbox, p)
    pm = PositionManager()
    _tick(AnyBot(pm, {}), hl, 3.05)
    pos = pm.positions["SUI"]
    assert pos.entry_reasons["exit_mode"] == "profits_only"
    assert pos.entry_reasons["exit_mode_requested"] == "bot_manages" and pos.entry_reasons["exit_mode_note"]
    assert ope.owner_exit_mode(pos) == "profits_only" and _fills(sandbox)[0]["exit_mode"] == "profits_only"
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_FORCE", "bot_manages")
    assert ope.owner_exit_mode(pos) == "profits_only"     # the kill-switch cannot hand it to a blind bot
    monkeypatch.setenv("OWNER_PLAN_EXIT_MODE_FORCE", "hands_off")
    assert ope.owner_exit_mode(pos) == "hands_off"


@pytest.mark.parametrize("row,expect", [
    (dict(coin="NOPE"), "is not a Hyperliquid perp"),
    (dict(coin="OLDCOIN"), "delisted"),
    (dict(coin="SUI", leverage=20), "above SUI's Hyperliquid max 10x"),
])
def test_rejections(sandbox, hl, on, row, expect):
    p = _sui("r", etype="market", entry=3.05, price_at_plan=3.05)
    p.update(row)
    _write_rows(sandbox, p)
    pm = PositionManager()
    _tick(AnyBot(pm, {}), hl, 3.05)
    st = _state(sandbox)["r"]
    assert st["status"] == "rejected" and expect in st["reason"] and pm.get_open_count() == 0


def test_hl_metadata_down_keeps_plan_queued(sandbox, hl, on):
    _write_rows(sandbox, _sui("w", etype="market", entry=3.05, price_at_plan=3.05))
    pm = PositionManager()
    bot = AnyBot(pm, {})
    hl.down = True
    _tick(bot, hl)
    assert _state(sandbox)["w"]["status"] == "queued" and "metadata" in _state(sandbox)["w"]["reason"]
    hl.down = False
    oac._META["tried"] = 0.0
    _tick(bot, hl, 3.05)
    assert _state(sandbox)["w"]["status"] == "open"


def test_risk_cap_clamp_applies(sandbox, hl, on, monkeypatch):
    monkeypatch.setenv("RISK_CAP_HARD_CLAMP", "true")
    monkeypatch.setenv("MAX_RISK_PCT_CEILING", "0.005")
    _write_rows(sandbox, _sui("rc", etype="market", entry=3.05, price_at_plan=3.05, stop=2.95, target=3.4))
    pm = PositionManager()
    _tick(AnyBot(pm, {}, equity=1000.0), hl, 3.05)          # 0.5% of $1000 = $5 < the plan's $20
    pos = pm.positions["SUI"]
    # clamped on the pre-fill price like the bot's own entry path; paper slippage (1bp) moves it marginally
    assert 4.5 < abs(pos.entry - pos.sl) * pos.qty <= 5.0 * 1.01


def test_off_scale_gap_needs_confirmation_then_is_honoured(sandbox, hl, on):
    _write_rows(sandbox, _sui("g", etype="market", entry=3.05, price_at_plan=3.05, stop=2.95, target=3.4))
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, 3.05)
    _tick(bot, hl, 2.60)                                    # -15% in one tick: held
    assert pm.positions["SUI"].state != "CLOSED" and bot._last_prices["SUI"] == 3.05
    _tick(bot, hl, 2.61)                                    # confirmed -> the stop fires
    assert [r["kind"] for r in _fills(sandbox)] == ["open", "final"]


# ── core coins: byte-identical with the flag on ─────────────────────────────

def _core_run(sandbox, hl):
    _write_rows(sandbox, _plan("e", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3150.0))
    pm = PositionManager()
    bot = AnyBot(pm, {"ETH": 3000.0})
    _tick(bot, hl)
    pos = pm.positions["ETH"]
    drop = {"ts", "position_id", "filled_at", "updated", "first_seen", "runner_checked"}
    st = {k: v for k, v in _state(sandbox)["e"].items() if k not in drop}
    fills = [{k: v for k, v in r.items() if k not in drop} for r in _fills(sandbox)]
    er = {k: v for k, v in pos.entry_reasons.items() if k not in drop}
    return (pos.entry, pos.qty, pos.sl, pos.tp1, pos.tp2, pos.atr, pos.trailing_distance), st, fills, er


def test_core_coin_identical_with_flag_on(tmp_path, monkeypatch, hl):
    import core.paths as paths
    out = []
    for i, flag in enumerate(("false", "true")):
        data = tmp_path / f"d{i}"
        (data / "hivemind").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(paths, "DATA_DIR", data)
        monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
        monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
        monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
        monkeypatch.setenv("OWNER_PLAN_ANY_COIN", flag)
        out.append(_core_run(data, hl))
    assert out[0] == out[1]
    assert "any_coin" not in out[1][3]
    assert hl.calls == [], "a core-coin plan must never touch the any-coin HL client"
