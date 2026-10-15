"""OWNER exit_style=runner on the bot's paper execution of owner plans (OWNER_RUNNER_STYLE).

runner: HALF of the original qty at +1R; the rest trails 1 daily ATR (atr_at_fill) behind the best price
since +1R, only ever the profitable way; the plan's own time limit closes what is left; the target closes
nothing. full: stop / target / time limit (unchanged). Flag off: byte-identical behaviour + shadow log.
Mirrors tools/hivemind/exit_style.play (checked against it at the end).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from execution.position_manager import PositionManager, Position  # noqa: E402

ATR = 100.0  # entry 3000, stop 2950 -> R = 50, +1R = 3050 (LONG) / 2950 (SHORT, stop 3050)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "hivemind").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    for k in ("OWNER_PLAN_EXIT_MODE_DEFAULT", "OWNER_PLAN_EXIT_MODE_FORCE", "BREAKEVEN_RATCHET",
              "OWNER_RUNNER_STYLE", "SL_FILL_FIDELITY_FIX"):
        monkeypatch.delenv(k, raising=False)
    return data


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "true")


def _pos(side="LONG", style="__missing__", mode="profits_only", owner=True, atr=ATR, qty=1.0):
    er = {}
    if owner:
        er = {"owner_plan_id": "p1", "owner_trade": True, "exit_mode": mode, "atr_at_fill": atr,
              "plan_max_hold_h": 48}
        if style != "__missing__":
            er["exit_style"] = style
    if side == "LONG":
        p = Position(symbol="ETH", side="LONG", entry=3000.0, qty=qty, sl=2950.0, tp1=3050.0, tp2=3150.0,
                     strategy=ope.OWNER_STRATEGY if owner else "llm_first", entry_reasons=er)
    else:
        p = Position(symbol="ETH", side="SHORT", entry=3000.0, qty=qty, sl=3050.0, tp1=2950.0, tp2=2850.0,
                     strategy=ope.OWNER_STRATEGY if owner else "llm_first", entry_reasons=er)
    p._transition("OPEN")
    p.highest_price = p.lowest_price = 3000.0
    return p


def _pm(pos):
    pm = PositionManager()
    pm.positions[pos.symbol] = pos
    return pm


def _rows(sandbox, source=None):
    p = sandbox / "hivemind" / "owner_exit_decisions.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    return [r for r in rows if source is None or r.get("source") == source]


def _mirror(side, px):
    """LONG price path -> the same path mirrored around entry 3000 for a SHORT."""
    return px if side == "LONG" else 6000.0 - px


# ── style resolution ────────────────────────────────────────────────────────

def test_style_resolution(sandbox, on):
    assert ope.owner_exit_style(_pos()) == "runner"                     # missing -> runner (default)
    assert ope.owner_exit_style(_pos(style="FULL")) == "full"
    assert ope.owner_exit_style(_pos(style="junk")) == "runner"
    assert ope.owner_exit_style(_pos(owner=False)) is None
    assert ope.runner_live(_pos()) and not ope.runner_live(_pos(style="full"))
    assert not ope.runner_live(_pos(mode="bot_manages")), "bot_manages keeps the bot's own machinery"
    assert not ope.runner_live(_pos(owner=False))


# ── the +1R half ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_half_taken_exactly_once_at_1r(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    stop0 = pos.sl
    # below +1R: nothing (in particular no TP1 leg at tp1 - for this geometry tp1 == +1R, test just under it)
    assert pm.update_price("ETH", _mirror(side, 3049.0)) == []
    assert pos.qty == pytest.approx(1.0) and pos.sl == stop0
    ev = pm.update_price("ETH", _mirror(side, 3050.0))
    assert [e.action for e in ev] == ["OWNER_RUNNER_HALF"]
    assert ev[0].qty == pytest.approx(0.5) and pos.qty == pytest.approx(0.5)
    assert not ev[0].is_position_close
    st = pos.entry_reasons["owner_runner"]
    assert st["half_taken"] and st["one_r"] == pytest.approx(_mirror(side, 3050.0))
    # never again, however far it runs (and the target closes nothing)
    for px in (3060.0, 3100.0, 3151.0, 3200.0, 3300.0):
        assert pm.update_price("ETH", _mirror(side, px)) == [], px
    assert pos.qty == pytest.approx(0.5) and pos.state != "CLOSED"


def test_half_counts_against_existing_partials_no_double_count(sandbox, on):
    """A leg banked before the flag was on (e.g. an old profits_only TP1 leg / AI partial of 30%) counts
    toward the half: only 20% more is closed at +1R, total partial = 50% of the original."""
    pos = _pos()
    pm = _pm(pos)
    pos.qty = 0.7  # 0.3 already partial-closed
    ev = pm.update_price("ETH", 3050.0)
    assert [e.action for e in ev] == ["OWNER_RUNNER_HALF"] and ev[0].qty == pytest.approx(0.2)
    # (partial_close rounds the REMAINDER down a lot-size tick on float dust: 0.7-0.2 -> 0.4999; pre-existing)
    assert pos.original_qty - pos.qty == pytest.approx(0.5, abs=2e-4)
    # cap already full: no leg at all, but the runner still arms its trail
    pos2 = _pos()
    pm2 = _pm(pos2)
    pos2.qty = 0.5
    assert pm2.update_price("ETH", 3050.0) == []
    assert pos2.entry_reasons["owner_runner"]["half_taken"] and pos2.qty == pytest.approx(0.5)


def test_bot_partials_blocked_while_runner_live(sandbox, on, monkeypatch):
    """The +1R half IS the 50%: no TP1 leg, no AI / heuristic partial on a live runner position."""
    pos = _pos()
    pm = _pm(pos)
    assert ope.owner_partial_allowance(pos) == 0.0
    assert pm.partial_close("ETH", 0.3, 3030.0, action="LLM_EXIT_PARTIAL") is None
    assert pos.qty == pytest.approx(1.0)
    from llm import exit_engine as ee
    from llm.exit_types import ExitDecision
    monkeypatch.setattr(ee, "_EXIT_LOG_FILE", str(sandbox / "exit_decisions.jsonl"))
    res = ee.ExitEngine().apply_exit_decision(
        ExitDecision(symbol="ETH", exit_action="partial", exit_confidence=0.9, partial_pct=0.3, reason="bank"),
        pos, 3030.0)
    assert not res["applied"] and "runner" in res["details"]
    assert pos.qty == pytest.approx(1.0)


# ── the trail ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_trail_only_ratchets_favourably(sandbox, on, side):
    sg = 1 if side == "LONG" else -1
    pos = _pos(side)
    pm = _pm(pos)
    stop0 = pos.sl
    pm.update_price("ETH", _mirror(side, 3050.0))                     # half; best 3050 -> cand 2950 == stop
    assert pos.sl == pytest.approx(stop0)
    pm.update_price("ETH", _mirror(side, 3120.0))                     # best 3120 -> trail 3020
    assert pos.sl == pytest.approx(_mirror(side, 3020.0))
    pm.update_price("ETH", _mirror(side, 3080.0))                     # pull-back: trail must NOT loosen
    assert pos.sl == pytest.approx(_mirror(side, 3020.0))
    pm.update_price("ETH", _mirror(side, 3200.0))                     # new best -> 3100
    assert pos.sl == pytest.approx(_mirror(side, 3100.0))
    seen = [pos.sl]
    for px in (3150.0, 3190.0, 3105.0, 3210.0):
        pm.update_price("ETH", _mirror(side, px))
        assert sg * (pos.sl - seen[-1]) >= 0, "trail moved the wrong way"
        seen.append(pos.sl)
    assert pos.sl == pytest.approx(_mirror(side, 3110.0))


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_trail_exit_closes_the_remainder(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    pm.update_price("ETH", _mirror(side, 3050.0))
    pm.update_price("ETH", _mirror(side, 3200.0))                     # trail 3100
    ev = pm.update_price("ETH", _mirror(side, 3099.0))
    assert [e.action for e in ev] == ["OWNER_RUNNER_TRAIL"]
    assert ev[0].is_position_close and ev[0].qty == pytest.approx(0.5) and pos.state == "CLOSED"


def test_stop_before_1r_is_the_owner_stop(sandbox, on):
    pos = _pos()
    pm = _pm(pos)
    pm.update_price("ETH", 3040.0)
    ev = pm.update_price("ETH", 2949.0)
    assert [e.action for e in ev] == ["SL"] and ev[0].qty == pytest.approx(1.0)


def test_no_atr_rides_owner_stop(sandbox, on):
    pos = _pos(atr=None)
    pm = _pm(pos)
    pm.update_price("ETH", 3050.0)
    pm.update_price("ETH", 3400.0)
    assert pos.sl == 2950.0 and pos.qty == pytest.approx(0.5) and pos.state != "CLOSED"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_time_limit_closes_the_remainder(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    pm.update_price("ETH", _mirror(side, 3050.0))
    pm.update_price("ETH", _mirror(side, 3120.0))
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=10)
    assert pm.check_hold_limits("ETH", _mirror(side, 3110.0), 48, "tighten_sl") is None
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=49)
    ev = pm.check_hold_limits("ETH", _mirror(side, 3110.0), 48, "tighten_sl")
    assert ev is not None and ev.action == "OWNER_PLAN_MAX_HOLD" and ev.qty == pytest.approx(0.5)
    assert pos.state == "CLOSED"


def test_restart_keeps_runner_state(sandbox, on):
    from execution.auto_recovery import _position_to_dict, _dict_to_position
    pos = _pos()
    pm = _pm(pos)
    pm.update_price("ETH", 3050.0)
    pm.update_price("ETH", 3150.0)
    back = _dict_to_position(json.loads(json.dumps(_position_to_dict(pos), default=str)))
    pm2 = _pm(back)
    assert pm2.update_price("ETH", 3140.0) == [], "half must not be re-taken after a restart"
    assert back.sl == pytest.approx(3050.0) and back.qty == pytest.approx(0.5)


# ── full style, flag off, bot positions ─────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_full_style_unchanged(sandbox, on, side):
    pos = _pos(side, style="full")
    pm = _pm(pos)
    ev = pm.update_price("ETH", _mirror(side, 3051.0))
    assert [e.action for e in ev] == ["TP1"]                           # old profits_only leg at tp1
    assert pos.sl == (2950.0 if side == "LONG" else 3050.0)
    ev = pm.update_price("ETH", _mirror(side, 3151.0))
    assert ev and ev[-1].action == "TP2" and pos.state == "CLOSED"
    assert "owner_runner" not in pos.entry_reasons


def _replay(pos, path):
    pm = _pm(pos)
    out = []
    for px in path:
        out.append([(e.action, round(e.qty, 6), round(e.price, 4)) for e in pm.update_price("ETH", px)])
    return out, (pos.state, round(pos.qty, 6), pos.sl, round(pos.realized_pnl, 6))


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_flag_off_is_byte_identical_and_shadow_logs(sandbox, monkeypatch, side):
    path = [_mirror(side, p) for p in (3020.0, 3051.0, 3120.0, 3200.0, 3080.0, 3151.0)]
    a = _replay(_pos(side), path)                                       # runner style, flag OFF
    b = _replay(_pos(side, style="full"), path)                         # full style: the old behaviour
    assert a == b
    assert "owner_runner" not in _pos(side).entry_reasons
    rows = _rows(sandbox, "owner_runner_shadow")
    acts = [r["exit_action"] for r in rows]
    assert acts.count("half_at_1r") == 1, acts
    assert "trail" in acts and "keep_runner" in acts
    assert all(r["applied"] is False and "[OWNER-RUNNER-SHADOW]" in r["details"] for r in rows)


def test_flag_off_shadow_reports_trail_close(sandbox):
    pos = _pos(mode="hands_off")      # hands_off: no TP1 leg / target ends it - runner would still trail
    pm = _pm(pos)
    for px in (3050.0, 3140.0, 3039.0):
        pm.update_price("ETH", px)
    acts = [r["exit_action"] for r in _rows(sandbox, "owner_runner_shadow")]
    assert acts[0] == "half_at_1r" and "close_remainder" in acts
    assert pos.qty == pytest.approx(1.0) and pos.sl == 2950.0 and pos.state != "CLOSED"


@pytest.mark.parametrize("flag", ["true", "false"])
def test_non_owner_positions_untouched(sandbox, monkeypatch, flag):
    monkeypatch.setenv("OWNER_RUNNER_STYLE", flag)
    pos = _pos(owner=False)
    pm = _pm(pos)
    ev = pm.update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"] and pos.sl > 2950.0     # bot machinery: TP1 + breakeven
    assert not _rows(sandbox)
    bm = _pos(mode="bot_manages")
    ev = _pm(bm).update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"] and "owner_runner" not in bm.entry_reasons


# ── open + fills accounting ─────────────────────────────────────────────────

@pytest.mark.parametrize("style,expect", [(None, "runner"), ("full", "full"), ("runner", "runner")])
def test_open_stores_style_and_atr(sandbox, monkeypatch, style, expect):
    from tests.test_owner_plan_exec import FakeBot
    import time
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (123.4, "test"))
    r = {"kind": "plan", "id": "rs1", "ts": time.time(), "coin": "ETH", "side": "LONG", "entry": 3000.0,
         "stop": 2950.0, "target": 3150.0, "price_at_plan": 3000.0, "entry_type": "market",
         "entry_window_h": 24, "leverage": 3, "risk_usd": 20.0, "setup": "breakout", "max_hold_h": 48}
    if style:
        r["exit_style"] = style
    (sandbox / "hivemind" / "owner_plans.jsonl").write_text(json.dumps(r) + "\n", encoding="utf-8")
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"ETH": 3000.0}))
    pos = pm.positions["ETH"]
    assert pos.entry_reasons["exit_style"] == expect and pos.entry_reasons["atr_at_fill"] == 123.4
    fills = [json.loads(l) for l in (sandbox / "hivemind" / "owner_fills.jsonl").read_text().splitlines()]
    assert fills[0]["exit_style"] == expect and fills[0]["atr_at_fill"] == 123.4


def test_atr_from_bot_daily_is_point_in_time():
    import pandas as pd
    t0 = pd.Timestamp("2026-09-01", tz="UTC")
    rows = [{"time": t0 + pd.Timedelta(days=i), "high": 110.0, "low": 90.0, "close": 100.0} for i in range(20)]
    rows[-1].update(high=1000.0, low=10.0)               # today's still-forming bar: must be ignored
    df = pd.DataFrame(rows)
    fill_ts = (t0 + pd.Timedelta(days=19, hours=6)).timestamp()
    assert ope._atr_from_daily_df(df, fill_ts) == pytest.approx(20.0)
    assert ope._atr_from_daily_df(df.drop(columns=["time"]), fill_ts) is None


def test_half_and_trail_recorded_as_partial_and_final(sandbox, on):
    import importlib
    pos = _pos()
    pos.entry_reasons["owner_plan_id"] = "pr1"
    pm = _pm(pos)
    evs = pm.update_price("ETH", 3050.0) + pm.update_price("ETH", 3200.0) + pm.update_price("ETH", 3099.0)
    rows = [ope.record_owner_close(e, pos, pm) for e in evs]
    assert [r["kind"] for r in rows] == ["partial", "final"]
    assert rows[0]["reason"] == "OWNER_RUNNER_HALF" and rows[1]["reason"] == "OWNER_RUNNER_TRAIL"
    assert rows[0]["qty"] + rows[1]["qty"] == pytest.approx(1.0)
    st = ope.load_state()["plans"]["pr1"]
    assert [f["kind"] for f in st["fills"]] == ["partial", "final"] and st["status"] == "closed"
    # tools/hivemind/plans.py exec_result reads the same legs
    sys.path.insert(0, str(BOT / "tools" / "hivemind"))
    import plans
    importlib.reload(plans)
    monkey_state, monkey_fills = plans.EXEC_STATE, plans.EXEC_FILLS
    try:
        plans.EXEC_STATE = ope.state_path()
        plans.EXEC_FILLS = ope.fills_path()
        er = plans._exec_results({})["pr1"]
    finally:
        plans.EXEC_STATE, plans.EXEC_FILLS = monkey_state, monkey_fills
    assert er["status"] == "closed" and [f["kind"] for f in er["fills"]] == ["partial", "final"]
    assert er["pnl_usd"] == pytest.approx(rows[1]["total_pnl"])


# ── parity with the graders' engine ─────────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_matches_exit_style_play(sandbox, on, side):
    """Same price path through exit_style.play (5m bars, close == high == low) and the bot: same legs."""
    xs = ope._exit_style_module()
    path = [_mirror(side, p) for p in (3010.0, 3049.0, 3050.0, 3151.0, 3230.0, 3190.0, 3240.0, 3139.0)]
    t0 = 1_700_000_000
    bars = [{"t": (t0 + 300 * (i + 1)) * 1000, "o": p, "h": p, "l": p, "c": p} for i, p in enumerate(path)]
    stop = 2950.0 if side == "LONG" else 3050.0
    tgt = 3150.0 if side == "LONG" else 2850.0
    pr = xs.play(side, 3000.0, stop, tgt, bars, t0, 48, "runner", ATR, now=t0 + 10 ** 6)
    pos = _pos(side)
    pm = _pm(pos)
    legs = []
    for p in path:
        for e in pm.update_price("ETH", p):
            legs.append((e.qty, e.price, e.action))
    assert [l["why"] for l in pr["legs"]] == ["half at +1R", "trail"]
    assert [round(l["frac"], 6) for l in pr["legs"]] == [round(q, 6) for q, _, _ in legs]
    assert [round(l["px"], 4) for l in pr["legs"]][0] == round(legs[0][1], 4)
    assert pos.state == "CLOSED" and legs[-1][2] == "OWNER_RUNNER_TRAIL"
    assert pr["trail"] == pytest.approx(pos.sl)
