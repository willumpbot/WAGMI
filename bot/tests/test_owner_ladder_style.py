"""OWNER exit_style=ladder ("quarters") on the graders' engine and the bot's paper execution (OWNER_LADDER_STYLE).

ladder: a QUARTER of the original qty at +0.5R, +0.75R and +1R (1R from the ACTUAL fill for the bot, the plan entry
for the graders); after the third quarter the last 25% trails 1 daily ATR (atr_at_fill) behind the best price,
starting from the plan stop, only ever the profitable way. Before any quarter the full position rides the plan
stop; the plan's time limit closes what is left; the target closes nothing. Target at/inside +1R of the fill ->
'full' (OWNER_RUNNER_TARGET_GUARD). Flag off: byte-identical to a 'full' position + shadow log only.
Every runner bug class from laptop reviews 154/158/159 is pinned here for the ladder too: persist after each step /
ratchet, idempotent recovery of recorded step rows BEFORE any SL/hold check, the stop-below-the-next-step case,
fill != entry + gap-bar parity with a bounded delta, managed_by stamps, untrailed stop labelled SL, hands_off live.
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

ATR = 100.0  # entry 3000, stop 2950 -> R = 50: +0.5R 3025, +0.75R 3037.5, +1R 3050 (LONG; mirrored for SHORT)
Q = ["OWNER_LADDER_Q1", "OWNER_LADDER_Q2", "OWNER_LADDER_Q3"]


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
              "OWNER_RUNNER_STYLE", "OWNER_LADDER_STYLE", "SL_FILL_FIDELITY_FIX", "OWNER_RUNNER_TARGET_GUARD"):
        monkeypatch.delenv(k, raising=False)
    return data


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")


@pytest.fixture
def saved(monkeypatch, tmp_path):
    """Route save_position_state to a temp file (the default live path is refused under pytest)."""
    import execution.auto_recovery as ar
    real = ar.save_position_state
    path = tmp_path / "position_state.json"
    calls = []

    def save(pm, filepath=None):
        calls.append(1)
        return real(pm, str(path))
    monkeypatch.setattr(ar, "save_position_state", save)
    return path, calls


def _pos(side="LONG", style="ladder", mode="profits_only", owner=True, atr=ATR, qty=1.0, pid="L1"):
    er = {}
    if owner:
        er = {"owner_plan_id": pid, "owner_trade": True, "exit_mode": mode, "atr_at_fill": atr,
              "plan_max_hold_h": 48, "runner_checked": 1.0}
        if style is not None:
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


def _m(side, px):
    """LONG price -> the same price mirrored around entry 3000 for a SHORT."""
    return px if side == "LONG" else 6000.0 - px


def _rows(sandbox, source=None):
    p = sandbox / "hivemind" / "owner_exit_decisions.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    return [r for r in rows if source is None or r.get("source") == source]


def _fills():
    """Parseable owner_fills.jsonl rows (a deliberately torn line is skipped, as recorded_ladder_steps does)."""
    p = ope.fills_path()
    out = []
    for l in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def _xs():
    return ope._exit_style_module()


def _bars(path, t0=1_700_000_000):
    return [{"t": (t0 + 300 * (i + 1)) * 1000, "o": p, "h": p, "l": p, "c": p} for i, p in enumerate(path)]


# ── the graders' engine (tools/hivemind/exit_style.play) ───────────────────────────────────────────

def test_engine_norm_and_guard(sandbox):
    xs = _xs()
    assert xs.norm("LADDER") == "ladder" and xs.norm("junk") == "runner" and xs.norm("full") == "full"
    assert xs.guarded("ladder", "LONG", 3000.0, 2950.0, 3150.0) == "ladder"
    assert xs.guarded("ladder", "LONG", 3000.0, 2950.0, 3050.0) == "full"      # target exactly at +1R
    assert xs.guarded("ladder", "LONG", 3000.0, 2950.0, 3040.0) == "full"      # inside +1R
    assert xs.guarded("ladder", "SHORT", 3000.0, 3050.0, 2960.0) == "full"


def test_engine_guard_kill_switch(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_RUNNER_TARGET_GUARD", "false")
    assert _xs().guarded("ladder", "LONG", 3000.0, 2950.0, 3040.0) == "ladder"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_engine_each_step_then_trail(sandbox, side):
    xs = _xs()
    t0 = 1_700_000_000
    path = [_m(side, p) for p in (3010, 3024, 3025, 3030, 3037.5, 3049, 3050, 3120, 3080, 3019)]
    pr = xs.play(side, 3000.0, _m(side, 2950.0), _m(side, 3150.0), _bars(path), t0, 48, "ladder", ATR,
                 now=t0 + 10 ** 6)
    assert [l["why"] for l in pr["legs"]] == ["quarter at +0.5R", "quarter at +0.75R", "quarter at +1R", "trail"]
    assert [l["frac"] for l in pr["legs"]] == [0.25, 0.25, 0.25, 0.25]
    assert [l["px"] for l in pr["legs"][:3]] == [_m(side, 3025.0), _m(side, 3037.5), _m(side, 3050.0)]
    assert pr["legs"][3]["px"] == pytest.approx(_m(side, 3020.0))              # best 3120 - 1 ATR
    assert pr["r"] == pytest.approx(round(0.25 * (0.5 + 0.75 + 1.0) + 0.25 * 0.4, 3))
    assert pr["status"] == "won" and xs.banked_frac(pr["legs"]) == 0.75


def test_engine_stop_before_any_step_and_between_steps(sandbox):
    xs = _xs()
    t0 = 1_700_000_000
    pr = xs.play("LONG", 3000.0, 2950.0, 3150.0, _bars([3010, 3024, 2949]), t0, 48, "ladder", ATR, now=t0 + 10 ** 6)
    assert [l["why"] for l in pr["legs"]] == ["stop"] and pr["legs"][0]["frac"] == 1.0 and pr["r"] == -1.0
    pr = xs.play("LONG", 3000.0, 2950.0, 3150.0, _bars([3026, 3040, 2949]), t0, 48, "ladder", ATR, now=t0 + 10 ** 6)
    assert [l["why"] for l in pr["legs"]] == ["quarter at +0.5R", "quarter at +0.75R", "stop"]
    assert pr["legs"][-1]["frac"] == pytest.approx(0.5) and pr["legs"][-1]["px"] == 2950.0   # plan stop, untrailed
    assert pr["r"] == pytest.approx(0.25 * 0.5 + 0.25 * 0.75 - 0.5, abs=1e-3)


def test_engine_gap_bar_banks_each_level_and_target_ignored(sandbox):
    xs = _xs()
    t0 = 1_700_000_000
    bars = [{"t": (t0 + 300) * 1000, "o": 3010, "h": 3200, "l": 3010, "c": 3190}]   # through all 3 + the target
    pr = xs.play("LONG", 3000.0, 2950.0, 3150.0, bars, t0, 48, "ladder", ATR, now=t0 + 10 ** 6)
    assert pr["status"] == "open" and pr["frac_left"] == pytest.approx(0.25)
    assert [l["px"] for l in pr["legs"]] == [3025.0, 3037.5, 3050.0]
    assert pr["trail"] == pytest.approx(3100.0)                                  # best 3200 - 1 ATR


def test_engine_time_limit_closes_rest(sandbox):
    xs = _xs()
    t0 = 1_700_000_000
    path = [3026] + [3030] * 30
    pr = xs.play("LONG", 3000.0, 2950.0, 3150.0, _bars(path), t0, 2, "ladder", ATR, now=t0 + 10 ** 6)
    assert [l["why"] for l in pr["legs"]] == ["quarter at +0.5R", "time limit"]
    assert pr["legs"][-1]["frac"] == pytest.approx(0.75) and pr.get("timed_out")
    assert pr["r"] == pytest.approx(round(0.25 * 0.5 + 0.75 * 0.6, 3))


def test_engine_partial_helpers(sandbox):
    xs = _xs()
    legs = [{"why": "quarter at +0.5R", "frac": 0.25}, {"why": "half at +1R", "frac": 0.5}, {"why": "trail", "frac": 0.25}]
    assert [xs.is_partial_leg(l) for l in legs] == [True, True, False]
    assert xs.banked_frac(legs) == 0.75 and xs.banked_frac([]) == 0.0


def test_runner_and_full_engine_unchanged(sandbox):
    """'runner' and 'full' play exactly as before the ladder (spot values of the pre-ladder engine)."""
    xs = _xs()
    t0 = 1_700_000_000
    path = [3010.0, 3049.0, 3050.0, 3151.0, 3230.0, 3190.0, 3240.0, 3139.0]
    r = xs.play("LONG", 3000.0, 2950.0, 3150.0, _bars(path), t0, 48, "runner", ATR, now=t0 + 10 ** 6)
    assert [(l["why"], l["frac"], l["px"]) for l in r["legs"]] == [("half at +1R", 0.5, 3050.0), ("trail", 0.5, 3140.0)]
    f = xs.play("LONG", 3000.0, 2950.0, 3150.0, _bars(path), t0, 48, "full", ATR, now=t0 + 10 ** 6)
    assert [(l["why"], l["frac"], l["px"]) for l in f["legs"]] == [("target", 1.0, 3150.0)]


def test_plans_create_accepts_ladder(sandbox, monkeypatch, tmp_path):
    sys.path.insert(0, str(BOT / "tools" / "hivemind"))
    import plans
    hm = tmp_path / "hm"
    monkeypatch.setattr(plans, "HM", hm)
    monkeypatch.setattr(plans, "PLANS", hm / "owner_plans.jsonl")
    monkeypatch.setattr(plans, "OUT", hm / "plans.json")
    base = {"coin": "ETH", "side": "LONG", "entry": 3000, "stop": 2950, "target": 3150}
    assert plans.create(dict(base, exit_style="ladder"))["exit_style"] == "ladder"
    assert plans.create(dict(base, entry=3001, exit_style="FULL"))["exit_style"] == "full"
    assert plans.create(dict(base, entry=3002))["exit_style"] == "runner"
    assert plans.create(dict(base, entry=3003, exit_style="junk"))["exit_style"] == "runner"


# ── bot: style resolution / flags ──────────────────────────────────────────────────────────────────

def test_style_resolution(sandbox, on):
    assert ope.normalize_exit_style("Ladder") == "ladder" and ope.owner_exit_style(_pos()) == "ladder"
    assert ope.ladder_live(_pos()) and not ope.runner_live(_pos())
    assert not ope.ladder_live(_pos(mode="bot_manages")), "bot_manages keeps the bot's own machinery"
    assert not ope.ladder_live(_pos(owner=False)) and not ope.ladder_live(_pos(style="runner"))


def test_flags_are_independent(sandbox, monkeypatch):
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "true")
    assert not ope.ladder_live(_pos()) and ope.ladder_applies(_pos())
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "false")
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")
    assert not ope.runner_live(_pos(style="runner")) and ope.ladder_live(_pos())


# ── bot: the steps ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_each_step_exactly_once(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    stop0 = pos.sl
    assert pm.update_price("ETH", _m(side, 3024.0)) == []
    for px, act, left in ((3025.0, Q[0], 0.75), (3037.5, Q[1], 0.5), (3050.0, Q[2], 0.25)):
        assert pm.update_price("ETH", _m(side, px - 0.1 if px != 3025.0 else 3024.9)) == []
        ev = pm.update_price("ETH", _m(side, px))
        assert [e.action for e in ev] == [act], px
        assert ev[0].qty == pytest.approx(0.25) and pos.qty == pytest.approx(left) and not ev[0].is_position_close
        assert pos.sl == stop0, "no step moves the stop"
    st = pos.entry_reasons["owner_ladder"]
    assert st["steps_taken"] == 3 and st["trail_on"] and pos.state == "TRAILING"
    assert [st[f"q{k}"]["level"] for k in (1, 2, 3)] == [_m(side, 3025.0), _m(side, 3037.5), _m(side, 3050.0)]
    for px in (3060.0, 3100.0, 3151.0, 3200.0):                       # past the target: target closes nothing
        assert pm.update_price("ETH", _m(side, px)) == [], px
    assert pos.qty == pytest.approx(0.25) and pos.state != "CLOSED"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_gap_tick_takes_every_reached_step(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    ev = pm.update_price("ETH", _m(side, 3045.0))                     # through +0.5R and +0.75R in one tick
    assert [e.action for e in ev] == Q[:2] and [e.qty for e in ev] == [pytest.approx(0.25)] * 2
    ev = pm.update_price("ETH", _m(side, 3070.0))
    assert [e.action for e in ev] == Q[2:] and pos.qty == pytest.approx(0.25)


def test_steps_count_against_existing_partials(sandbox, on):
    """A leg banked before (e.g. an old TP1 leg of 30%) counts: q1 closes nothing (0.25 cum already banked), q2
    closes 0.2, q3 0.25 - cumulative 75% of the original, never more."""
    pos = _pos()
    pos.qty = 0.7
    pm = _pm(pos)
    assert pm.update_price("ETH", 3025.0) == []
    assert pos.entry_reasons["owner_ladder"]["steps_taken"] == 1
    ev = pm.update_price("ETH", 3037.5)
    assert [e.action for e in ev] == [Q[1]] and ev[0].qty == pytest.approx(0.2)
    ev = pm.update_price("ETH", 3050.0)
    assert [e.action for e in ev] == [Q[2]]
    assert pos.original_qty - pos.qty == pytest.approx(0.75, abs=2e-4)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_trail_after_q3_only_ratchets_favourably_then_closes(sandbox, on, side):
    sg = 1 if side == "LONG" else -1
    pos = _pos(side)
    pm = _pm(pos)
    stop0 = pos.sl
    pm.update_price("ETH", _m(side, 3030.0))
    pm.update_price("ETH", _m(side, 3040.0))
    assert pos.sl == stop0, "no trail before the third quarter"
    pm.update_price("ETH", _m(side, 3050.0))                          # q3; best 3050 - 100 == stop
    assert pos.sl == pytest.approx(stop0)
    pm.update_price("ETH", _m(side, 3120.0))
    assert pos.sl == pytest.approx(_m(side, 3020.0))
    pm.update_price("ETH", _m(side, 3080.0))
    assert pos.sl == pytest.approx(_m(side, 3020.0)), "trail must not loosen"
    seen = [pos.sl]
    for px in (3150.0, 3190.0, 3105.0, 3210.0):
        pm.update_price("ETH", _m(side, px))
        assert sg * (pos.sl - seen[-1]) >= 0
        seen.append(pos.sl)
    assert pos.sl == pytest.approx(_m(side, 3110.0))
    ev = pm.update_price("ETH", _m(side, 3109.0))
    assert [e.action for e in ev] == ["OWNER_LADDER_TRAIL"] and ev[0].is_position_close
    assert ev[0].qty == pytest.approx(0.25) and pos.state == "CLOSED"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_stop_before_any_step_is_the_owner_stop(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    pm.update_price("ETH", _m(side, 3020.0))
    ev = pm.update_price("ETH", _m(side, 2949.0))
    assert [e.action for e in ev] == ["SL"] and ev[0].qty == pytest.approx(1.0)


def test_stop_between_steps_closes_the_rest_at_the_plan_stop(sandbox, on):
    pos = _pos()
    pm = _pm(pos)
    pm.update_price("ETH", 3026.0)
    pm.update_price("ETH", 3038.0)
    ev = pm.update_price("ETH", 2949.0)
    assert [e.action for e in ev] == ["SL"] and ev[0].qty == pytest.approx(0.5)
    assert ope.managed_by(ev[0].action) == "stop"


def test_untrailed_stop_after_q3_is_labelled_sl(sandbox, on):
    pos = _pos()
    pm = _pm(pos)
    pm.update_price("ETH", 3050.0)                                    # all three quarters, trail == owner stop
    assert pos.sl == 2950.0
    ev = pm.update_price("ETH", 2949.0)
    assert [e.action for e in ev] == ["SL"] and ev[0].qty == pytest.approx(0.25)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_time_limit_closes_the_remainder(sandbox, on, side):
    pos = _pos(side)
    pm = _pm(pos)
    pm.update_price("ETH", _m(side, 3030.0))                          # q1 only
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=10)
    assert pm.check_hold_limits("ETH", _m(side, 3030.0), 48, "tighten_sl") is None
    pos.open_time = datetime.now(timezone.utc) - timedelta(hours=49)
    ev = pm.check_hold_limits("ETH", _m(side, 3030.0), 48, "tighten_sl")
    assert ev is not None and ev.action == "OWNER_PLAN_MAX_HOLD" and ev.qty == pytest.approx(0.75)
    assert pos.state == "CLOSED"


def test_bot_partials_blocked_while_ladder_live(sandbox, on, monkeypatch):
    pos = _pos()
    pm = _pm(pos)
    assert ope.owner_partial_allowance(pos) == 0.0
    assert pm.partial_close("ETH", 0.3, 3020.0, action="LLM_EXIT_PARTIAL") is None
    from llm import exit_engine as ee
    from llm.exit_types import ExitDecision
    monkeypatch.setattr(ee, "_EXIT_LOG_FILE", str(sandbox / "exit_decisions.jsonl"))
    res = ee.ExitEngine().apply_exit_decision(
        ExitDecision(symbol="ETH", exit_action="partial", exit_confidence=0.9, partial_pct=0.3, reason="bank"),
        pos, 3020.0)
    assert not res["applied"] and "ladder" in res["details"]
    ev = pm.update_price("ETH", 3051.0)                               # no TP1 leg either: only the quarters
    assert [e.action for e in ev] == Q and pos.qty == pytest.approx(0.25)


# ── guard / readiness (shared with the runner) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("target,guard,expect", [
    (3040.0, None, "full"), (3050.0, None, "full"), (3040.0, "false", "ladder"), (3150.0, None, "ladder")])
def test_target_guard_on_existing_position(sandbox, on, monkeypatch, target, guard, expect):
    if guard is not None:
        monkeypatch.setenv("OWNER_RUNNER_TARGET_GUARD", guard)
    pos = _pos()
    pos.entry_reasons.pop("runner_checked")
    pos.tp2 = target
    pos.entry_reasons["plan_target"] = target
    assert ope.ladder_live(pos) == (expect == "ladder")
    assert pos.entry_reasons["exit_style"] == expect
    if expect == "full":
        assert "OWNER_RUNNER_TARGET_GUARD" in pos.entry_reasons["exit_style_reason"]
        ev = _pm(pos).update_price("ETH", target)                     # full: the target closes it (after TP1 leg)
        assert ev and ev[-1].action == "TP2"


def test_no_atr_degrades_to_full(sandbox, on, monkeypatch):
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (None, "unavailable"))
    monkeypatch.setenv("OWNER_RUNNER_ATR_RETRIES", "1")
    pos = _pos(atr=None)
    pos.entry_reasons.pop("runner_checked")
    pm = _pm(pos)
    pm.update_price("ETH", 3010.0)
    assert pos.entry_reasons["exit_style"] == "full" and "a ladder needs a trail width" in pos.entry_reasons["exit_style_reason"]
    assert "owner_ladder" not in pos.entry_reasons
    ev = pm.update_price("ETH", 3151.0)
    assert ev and ev[-1].action == "TP2" and pos.state == "CLOSED"


def test_missing_atr_backfills_point_in_time(sandbox, on, monkeypatch):
    seen = {}

    def fake(bot, coin, ts):
        seen["ts"] = ts
        return 100.0, "hl_1d"
    monkeypatch.setattr(ope, "atr_at_fill", fake)
    pos = _pos(atr=None)
    pos.entry_reasons.pop("runner_checked")
    pos.open_time = datetime(2026, 10, 14, 0, 35, 59, tzinfo=timezone.utc)
    ev = _pm(pos).update_price("ETH", 3050.0)
    assert seen["ts"] == pytest.approx(pos.open_time.timestamp()), "ATR as known AT THE FILL"
    assert pos.entry_reasons["atr_at_fill_source"] == "backfill_hl_1d" and pos.entry_reasons["exit_style"] == "ladder"
    assert [e.action for e in ev] == Q


def _drain_one(sandbox, monkeypatch, atr, target=3150.0, style="ladder", price=3000.0):
    from tests.test_owner_plan_exec import FakeBot
    import time
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (atr, "test" if atr else "unavailable"))
    r = {"kind": "plan", "id": "g1", "ts": time.time(), "coin": "ETH", "side": "LONG", "entry": 3000.0,
         "stop": 2950.0, "target": target, "price_at_plan": price, "entry_type": "market",
         "entry_window_h": 24, "leverage": 3, "risk_usd": 20.0, "setup": "breakout", "max_hold_h": 48,
         "exit_style": style}
    (sandbox / "hivemind" / "owner_plans.jsonl").write_text(json.dumps(r) + "\n", encoding="utf-8")
    pm = PositionManager()
    ope.drain(FakeBot(pm, {"ETH": price}))
    return pm.positions["ETH"], _fills()[0]


def test_open_stores_ladder_style_and_atr(sandbox, monkeypatch):
    pos, row = _drain_one(sandbox, monkeypatch, atr=123.4)
    assert pos.entry_reasons["exit_style"] == "ladder" and row["exit_style"] == "ladder" and row["atr_at_fill"] == 123.4


def test_open_guard_degrades_to_full(sandbox, monkeypatch):
    pos, row = _drain_one(sandbox, monkeypatch, atr=100.0, target=3045.0)
    assert row["exit_style"] == "full" and "OWNER_RUNNER_TARGET_GUARD" in row["exit_style_reason"]


def test_open_atr_failure_degrades_to_full(sandbox, monkeypatch):
    pos, row = _drain_one(sandbox, monkeypatch, atr=None)
    assert row["exit_style"] == "full" and "atr_at_fill" in row["exit_style_reason"]


# ── crash safety ───────────────────────────────────────────────────────────────────────────────────

def test_state_persisted_after_each_step_and_each_ratchet(sandbox, on, saved):
    path, calls = saved
    pos = _pos()
    pm = _pm(pos)
    for px, k, left in ((3025.0, 1, 0.75), (3037.5, 2, 0.5), (3050.0, 3, 0.25)):
        n = len(calls)
        pm.update_price("ETH", px)
        assert len(calls) == n + 1, k
        st = json.loads(path.read_text())["positions"]["ETH"]
        assert st["qty"] == pytest.approx(left) and st["entry_reasons"]["owner_ladder"]["steps_taken"] == k
    n = len(calls)
    pm.update_price("ETH", 3120.0)                                    # ratchet -> 3020
    assert len(calls) == n + 1 and json.loads(path.read_text())["positions"]["ETH"]["sl"] == pytest.approx(3020.0)
    pm.update_price("ETH", 3100.0)                                    # no ratchet -> no save
    assert len(calls) == n + 1


def _snap(pos):
    from execution.auto_recovery import _position_to_dict
    return json.loads(json.dumps(_position_to_dict(pos), default=str))


def _restore(snapshot):
    from execution.auto_recovery import _dict_to_position
    return _dict_to_position(snapshot)


def test_crash_after_step_row_before_save_never_refires(sandbox, on):
    """Save before q1, take q1 (its 'partial' row lands), crash, restore the pre-q1 state, replay: no re-fire;
    then the remaining steps fire once each -> exactly ONE row per step."""
    pos = _pos()
    pos.position_id = "lp-1"
    pm = _pm(pos)
    pm.update_price("ETH", 3010.0)
    snapshot = _snap(pos)
    evs = pm.update_price("ETH", 3025.0)
    assert [e.action for e in evs] == [Q[0]]
    rows = [ope.record_owner_close(e, pos, pm) for e in evs]
    assert rows[0]["managed_by"] == "ladder_q1" and rows[0]["exit_style"] == "ladder"
    banked = pos.realized_pnl
    back = _restore(snapshot)                                         # --- crash ---
    assert back.qty == pytest.approx(1.0) and not (back.entry_reasons.get("owner_ladder") or {}).get("steps_taken")
    pm2 = _pm(back)
    assert pm2.update_price("ETH", 3025.0) + pm2.update_price("ETH", 3030.0) == []
    assert back.qty == pytest.approx(0.75) and back.realized_pnl == pytest.approx(banked)
    assert back.entry_reasons["owner_ladder"]["q1"]["recovered_from_fills"]
    for px in (3037.5, 3050.0):
        for e in pm2.update_price("ETH", px):
            ope.record_owner_close(e, back, pm2)
    fills = _fills()
    assert [f["reason"] for f in fills] == Q, "exactly one row per step"
    assert back.qty == pytest.approx(0.25) and back.state == "TRAILING"


def test_crash_after_gap_tick_recovers_both_steps(sandbox, on):
    pos = _pos()
    pos.position_id = "lp-2"
    pm = _pm(pos)
    snapshot = _snap(pos)
    evs = pm.update_price("ETH", 3045.0)                              # q1 + q2 in one tick
    for e in evs:
        ope.record_owner_close(e, pos, pm)
    back = _restore(snapshot)
    pm2 = _pm(back)
    assert pm2.update_price("ETH", 3045.0) == []
    assert back.qty == pytest.approx(0.5) and back.entry_reasons["owner_ladder"]["steps_taken"] == 2
    for k in ("realized_pnl", "fees_paid", "funding_costs"):
        assert getattr(back, k) == pytest.approx(getattr(pos, k), abs=1e-5), k


def test_crash_after_q3_recovers_and_arms_trail(sandbox, on):
    pos = _pos()
    pos.position_id = "lp-3"
    pm = _pm(pos)
    snapshot = _snap(pos)
    for e in pm.update_price("ETH", 3060.0):                          # all three in one tick
        ope.record_owner_close(e, pos, pm)
    back = _restore(snapshot)
    pm2 = _pm(back)
    assert pm2.update_price("ETH", 3200.0) == []
    st = back.entry_reasons["owner_ladder"]
    assert st["steps_taken"] == 3 and st["trail_on"] and back.qty == pytest.approx(0.25)
    assert back.sl == pytest.approx(3100.0) and back.state == "TRAILING"
    ev = pm2.update_price("ETH", 3099.0)
    assert [e.action for e in ev] == ["OWNER_LADDER_TRAIL"] and ev[0].qty == pytest.approx(0.25)


@pytest.mark.parametrize("closer", ["stop", "time"])
def test_restore_with_recorded_step_then_stop_before_next_step(sandbox, on, closer):
    """Laptop-158 class: the step's save was lost but its row exists; after restore price goes to the STOP (or the
    time limit) WITHOUT reaching the next step. One 0.25 partial + one 0.75 final, total == original, books equal
    to the no-crash reference (fee / funding shares carried)."""
    pos = _pos()
    pos.position_id = "lp-4"
    pos.funding_costs = 0.8
    pm = _pm(pos)
    pm.update_price("ETH", 3010.0)
    snapshot = _snap(pos)
    evs = pm.update_price("ETH", 3025.0)
    row = ope.record_owner_close(evs[0], pos, pm)
    assert row["fee"] > 0 and row["funding"] == pytest.approx(0.2)
    back = _restore(snapshot)                                         # --- crash ---
    pm2 = _pm(back)
    if closer == "stop":
        out = pm2.update_price("ETH", 2949.0)
    else:
        back.open_time = datetime.now(timezone.utc) - timedelta(hours=49)
        out = [pm2.check_hold_limits("ETH", 3010.0, 48, "tighten_sl")]   # hold check FIRST, no tick before it
    assert len(out) == 1 and out[0].is_position_close
    assert out[0].qty == pytest.approx(0.75), "final leg is what is left, not the full size"
    final = ope.record_owner_close(out[0], back, pm2)
    fills = _fills()
    assert [(f["kind"], f["qty"]) for f in fills] == [("partial", pytest.approx(0.25)), ("final", pytest.approx(0.75))]
    assert sum(f["qty"] for f in fills) == pytest.approx(back.original_qty)
    if closer == "stop":
        ref = pm.update_price("ETH", 2949.0)
    else:
        pos.open_time = back.open_time
        ref = [pm.check_hold_limits("ETH", 3010.0, 48, "tighten_sl")]
    assert ref[0].qty == pytest.approx(out[0].qty)
    for k in ("fees_paid", "funding_costs", "realized_pnl"):
        assert getattr(back, k) == pytest.approx(getattr(pos, k), abs=1e-5), k
    assert final["total_pnl"] == pytest.approx(back.realized_pnl, abs=1e-5)


def test_recorded_steps_of_other_plan_or_runner_rows_ignored(sandbox, on):
    ope._append_fill({"kind": "partial", "plan_id": "other", "reason": "OWNER_LADDER_Q1", "qty": 0.25,
                      "exit": 3025.0, "pnl": 6.0, "position_id": "x"})
    ope._append_fill({"kind": "partial", "plan_id": "L1", "reason": "OWNER_RUNNER_HALF", "qty": 0.5,
                      "exit": 3050.0, "pnl": 25.0})
    assert ope.recorded_ladder_steps("L1") == {}
    pos = _pos()
    pos.entry_reasons["exit_style"] = "ladder"
    ev = _pm(pos).update_price("ETH", 3025.0)
    assert [e.action for e in ev] == [Q[0]]
    # no stray runner half stripped 50% first: only the quarter left the position, and only its PnL is booked
    assert pos.qty == pytest.approx(0.75) and "owner_runner" not in pos.entry_reasons
    assert pos.realized_pnl == pytest.approx(ev[0].pnl - ev[0].fee, abs=1e-9)
    assert ev[0].pnl == pytest.approx(25.0 * 0.25)


def test_runner_position_ignores_ladder_rows(sandbox, monkeypatch):
    """Reverse cross-apply: a RUNNER position whose plan id carries ladder step rows is untouched by them."""
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "true")
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")
    for k, px in ((1, 3025.0), (2, 3037.5)):
        ope._append_fill({"kind": "partial", "plan_id": "R1", "reason": Q[k - 1], "qty": 0.25, "exit": px,
                          "pnl": 6.0, "fee": 0.1, "position_id": ""})
    pos = _pos(style="runner", pid="R1")
    pm = _pm(pos)
    assert pm.update_price("ETH", 3040.0) == []
    assert pos.qty == pytest.approx(1.0) and pos.realized_pnl == 0.0 and pos.fees_paid == 0.0
    assert "owner_ladder" not in pos.entry_reasons
    ev = pm.update_price("ETH", 3050.0)
    assert [e.action for e in ev] == ["OWNER_RUNNER_HALF"] and pos.qty == pytest.approx(0.5)


def test_torn_middle_row_recovers_only_contiguous_steps(sandbox, on):
    """Laptop 178 A1: owner_fills.jsonl has q1 and q3 but q2's row is torn (unparseable). Restore pre-q1: only q1 is
    recovered (steps_taken 1, qty 0.75, trail NOT armed); the live loop then re-fires q2 at its level; q3 (recorded)
    is never re-fired past that point... it fires live once q2 is taken, exactly as a fresh step."""
    pos = _pos()
    pos.position_id = "lp-torn"
    pm = _pm(pos)
    snapshot = _snap(pos)
    evs = pm.update_price("ETH", 3060.0)                              # q1, q2, q3 in one tick
    rows = [ope.record_owner_close(e, pos, pm) for e in evs]
    lines = ope.fills_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    lines[1] = lines[1][: len(lines[1]) // 2]                         # tear the MIDDLE (q2) row
    ope.fills_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert sorted(ope.recorded_ladder_steps("L1", "lp-torn")) == [1, 3]
    back = _restore(snapshot)
    pm2 = _pm(back)
    assert pm2.update_price("ETH", 3030.0) == []                      # below q2: nothing fires
    st = back.entry_reasons["owner_ladder"]
    assert st["steps_taken"] == 1 and not st.get("trail_on") and back.qty == pytest.approx(0.75)
    assert back.realized_pnl == pytest.approx(rows[0]["pnl"], abs=1e-5)
    assert back.state == "OPEN" and back.sl == 2950.0
    ev = pm2.update_price("ETH", 3037.5)                              # the missing quarter re-fires at its level...
    assert [e.action for e in ev] == [Q[1]]
    for e in ev:
        ope.record_owner_close(e, back, pm2)
    # ...which makes the recorded q3 contiguous: applied from its row (it really filled), never re-fired
    st = back.entry_reasons["owner_ladder"]
    assert st["steps_taken"] == 3 and st["q3"]["recovered_from_fills"] and st["trail_on"]
    assert back.qty == pytest.approx(0.25) and back.state == "TRAILING"
    assert pm2.update_price("ETH", 3060.0) == []
    parsed = [f["reason"] for f in _fills()]
    assert sorted(parsed) == sorted(Q), "one parseable row per step (q1, q3 original; q2 re-fired)"
    assert sum(f["qty"] for f in _fills()) == pytest.approx(0.75)
    assert back.realized_pnl == pytest.approx(sum(f["pnl"] for f in _fills()), abs=1e-5)


def test_flag_off_crash_recovery_is_flag_independent(sandbox, monkeypatch):
    """Laptop 178 A2: q1 fired LIVE, its row landed, the save was lost; the bot restarts with OWNER_LADDER_STYLE
    unset (full machinery). A stop must close exactly what is left (0.75), not the original size."""
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")
    pos = _pos()
    pos.position_id = "lp-off"
    pm = _pm(pos)
    snapshot = _snap(pos)
    evs = pm.update_price("ETH", 3025.0)
    assert [e.action for e in evs] == [Q[0]]
    ope.record_owner_close(evs[0], pos, pm)
    monkeypatch.delenv("OWNER_LADDER_STYLE")                          # --- crash; restart with the flag off ---
    back = _restore(snapshot)
    pm2 = _pm(back)
    out = pm2.update_price("ETH", 2949.0)
    assert [e.action for e in out] == ["SL"] and out[0].qty == pytest.approx(0.75)
    assert back.entry_reasons["owner_ladder"]["q1"]["recovered_from_fills"]
    final = ope.record_owner_close(out[0], back, pm2)
    fills = _fills()
    assert [(f["kind"], f["qty"]) for f in fills] == [("partial", pytest.approx(0.25)), ("final", pytest.approx(0.75))]
    assert final["total_pnl"] == pytest.approx(back.realized_pnl, abs=1e-5)


def test_restart_keeps_ladder_state(sandbox, on):
    pos = _pos()
    pm = _pm(pos)
    pm.update_price("ETH", 3050.0)
    pm.update_price("ETH", 3150.0)
    back = _restore(_snap(pos))
    assert _pm(back).update_price("ETH", 3140.0) == [], "no step re-fires after a restart"
    assert back.sl == pytest.approx(3050.0) and back.qty == pytest.approx(0.25)


# ── fills accounting / hands_off ───────────────────────────────────────────────────────────────────

def test_managed_by_labels():
    assert [ope.managed_by(a) for a in Q + ["OWNER_LADDER_TRAIL"]] == ["ladder_q1", "ladder_q2", "ladder_q3",
                                                                       "ladder_trail"]
    assert ope.managed_by("OWNER_RUNNER_HALF") == "runner_half"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_ladder_live_under_hands_off_rows(sandbox, on, side):
    pos = _pos(side, mode="hands_off", pid="ho1")
    pm = _pm(pos)
    assert ope.ladder_live(pos) and ope.owner_partial_allowance(pos) == 0.0
    evs = []
    for px in (3025.0, 3037.5, 3050.0, 3200.0, 3099.0):
        evs += pm.update_price("ETH", _m(side, px))
    rows = [ope.record_owner_close(e, pos, pm) for e in evs]
    assert [(r["kind"], r["managed_by"]) for r in rows] == [("partial", "ladder_q1"), ("partial", "ladder_q2"),
                                                            ("partial", "ladder_q3"), ("final", "ladder_trail")]
    assert all(r["exit_mode"] == "hands_off" and r["exit_style"] == "ladder" for r in rows)
    assert sum(r["qty"] for r in rows) == pytest.approx(1.0)
    st = ope.load_state()["plans"]["ho1"]
    assert st["status"] == "closed" and len(st["fills"]) == 4


# ── parity bot vs exit_style.play ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_matches_exit_style_play(sandbox, on, side):
    xs = _xs()
    path = [_m(side, p) for p in (3010.0, 3025.0, 3030.0, 3037.5, 3050.0, 3151.0, 3230.0, 3190.0, 3240.0, 3139.0)]
    t0 = 1_700_000_000
    pr = xs.play(side, 3000.0, _m(side, 2950.0), _m(side, 3150.0), _bars(path, t0), t0, 48, "ladder", ATR,
                 now=t0 + 10 ** 6)
    pos = _pos(side)
    pm = _pm(pos)
    legs = [e for p in path for e in pm.update_price("ETH", p)]
    assert [l["why"] for l in pr["legs"]] == ["quarter at +0.5R", "quarter at +0.75R", "quarter at +1R", "trail"]
    assert [e.action for e in legs] == Q + ["OWNER_LADDER_TRAIL"]
    assert [round(l["frac"], 6) for l in pr["legs"]] == [round(e.qty, 6) for e in legs]
    assert [round(l["px"], 4) for l in pr["legs"][:3]] == [round(e.price, 4) for e in legs[:3]]
    assert pos.state == "CLOSED" and pr["trail"] == pytest.approx(pos.sl)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_parity_known_delta_fill_slip_and_gap(sandbox, on, side):
    """Declared live-vs-graded drift: the bot measures R from its ACTUAL fill (10 worse than the plan entry) and sees
    one price per tick, so a bar that GAPS through several levels fills each step at the tick, not at the level.
    play() (plan entry, bar highs/lows) takes every step exactly at its level. Known delta per step: never at a
    worse price than play's (sign) and at most the gap overshoot + fill slip (bound). Same legs, same fractions,
    both trails converge on best - 1 ATR."""
    sg = 1 if side == "LONG" else -1
    xs = _xs()
    m = lambda p: _m(side, p)  # noqa: E731
    plan_entry, fill, stop, tgt = m(3000.0), m(3010.0), m(2950.0), m(3300.0)
    # bar 3 GAPS from 3020 to 3045..3100, through every level (plan 3025/3037.5/3050; fill 3040/3055/3070)
    raw = [(3015, 3022, 3012, 3020), (3020, 3021, 3018, 3020), (3045, 3100, 3045, 3095),
           (3095, 3180, 3095, 3180), (3180, 3180, 3070, 3070)]
    t0 = 1_700_000_000
    bars = []
    for i, (o, h, l, c) in enumerate(raw):
        hi, lo = (m(h), m(l)) if side == "LONG" else (m(l), m(h))
        bars.append({"t": (t0 + 300 * (i + 1)) * 1000, "o": m(o), "h": hi, "l": lo, "c": m(c)})
    pr = xs.play(side, plan_entry, stop, tgt, bars, t0, 48, "ladder", ATR, now=t0 + 10 ** 6)
    pos = _pos(side)
    pos.entry = fill
    pos.tp2 = tgt
    pos.entry_reasons["plan_target"] = tgt
    pm = _pm(pos)
    legs = [e for b in bars for e in pm.update_price("ETH", b["c"])]
    assert [l["why"] for l in pr["legs"]] == ["quarter at +0.5R", "quarter at +0.75R", "quarter at +1R", "trail"]
    assert [e.action for e in legs] == Q + ["OWNER_LADDER_TRAIL"]
    assert [round(l["frac"], 6) for l in pr["legs"]] == [round(e.qty, 6) for e in legs]
    gap_hi = bars[2]["h"] if sg > 0 else bars[2]["l"]
    risk_b = abs(fill - stop)
    deltas = []
    for (k_r, e, l) in zip((0.5, 0.75, 1.0), legs[:3], pr["legs"][:3]):
        play_lvl = plan_entry + sg * k_r * abs(plan_entry - stop)
        assert l["px"] == pytest.approx(play_lvl)
        bot_lvl = fill + sg * k_r * risk_b
        assert sg * (e.price - bot_lvl) >= 0, "bot step fills at/through ITS level (R from the fill)"
        d = sg * (e.price - l["px"])
        assert d >= 0, "bot's step is never at a worse price than the graded level"
        assert d <= sg * (gap_hi - play_lvl) + abs(fill - plan_entry) + 1e-9, "bounded by gap overshoot + fill slip"
        deltas.append(d)
    assert max(deltas) > 0, "the gap makes the drift real (cannot be zeroed by construction)"
    assert pos.entry_reasons["owner_ladder"]["q3"]["level"] == pytest.approx(fill + sg * risk_b)
    assert pr["trail"] == pytest.approx(m(3080.0)) and pos.sl == pytest.approx(m(3080.0))


# ── flag off: byte-identical + shadow; other styles untouched ──────────────────────────────────────

def _replay(pos, path):
    pm = _pm(pos)
    out = [[(e.action, round(e.qty, 6), round(e.price, 4)) for e in pm.update_price("ETH", px)] for px in path]
    return out, (pos.state, round(pos.qty, 6), pos.sl, round(pos.realized_pnl, 6))


@pytest.mark.parametrize("runner_flag", [None, "true"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_flag_off_is_byte_identical_to_full_and_shadow_logs(sandbox, monkeypatch, side, runner_flag):
    if runner_flag:
        monkeypatch.setenv("OWNER_RUNNER_STYLE", runner_flag)        # the runner flag never acts on a ladder
    path = [_m(side, p) for p in (3020.0, 3026.0, 3038.0, 3051.0, 3120.0, 3200.0, 3080.0, 3151.0)]
    persists = []
    monkeypatch.setattr(PositionManager, "_persist_owner_runner_state", lambda self: persists.append(1))
    lad = _pos(side)
    a = _replay(lad, path)                                              # ladder style, OWNER_LADDER_STYLE off
    b = _replay(_pos(side, style="full"), path)                         # full style: the old behaviour
    assert a == b
    assert "owner_ladder" not in lad.entry_reasons, "the TICKED ladder position carries no ladder state"
    assert not persists, "no ladder/runner persistence fired with the flag off"
    rows = _rows(sandbox, "owner_ladder_shadow")
    acts = [r["exit_action"] for r in rows]
    assert [acts.count(f"quarter_{k}") for k in (1, 2, 3)] == [1, 1, 1], acts
    assert "trail" in acts and "keep_ladder" in acts
    assert all(r["applied"] is False and "[OWNER-LADDER-SHADOW]" in r["details"] for r in rows)
    assert not ope.fills_path().exists()


def test_flag_off_shadow_reports_trail_close(sandbox):
    pos = _pos(mode="hands_off")
    pm = _pm(pos)
    for px in (3050.0, 3140.0, 3039.0):
        pm.update_price("ETH", px)
    acts = [r["exit_action"] for r in _rows(sandbox, "owner_ladder_shadow")]
    assert acts[:3] == ["quarter_1", "quarter_2", "quarter_3"] and "close_remainder" in acts
    assert pos.qty == pytest.approx(1.0) and pos.sl == 2950.0 and pos.state != "CLOSED"


@pytest.mark.parametrize("style", ["runner", "full"])
@pytest.mark.parametrize("runner_flag", ["false", "true"])
def test_ladder_flag_never_touches_runner_or_full(sandbox, monkeypatch, style, runner_flag):
    path = [3020.0, 3026.0, 3038.0, 3051.0, 3120.0, 3200.0, 3080.0, 3151.0, 3099.0]
    monkeypatch.setenv("OWNER_RUNNER_STYLE", runner_flag)
    monkeypatch.setenv("OWNER_LADDER_STYLE", "false")
    a = _replay(_pos(style=style, pid="r1"), path)
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")
    b = _replay(_pos(style=style, pid="r1"), path)
    assert a == b
    assert not _rows(sandbox, "owner_ladder_shadow")


@pytest.mark.parametrize("flag", ["true", "false"])
def test_non_owner_positions_untouched(sandbox, monkeypatch, flag):
    monkeypatch.setenv("OWNER_LADDER_STYLE", flag)
    pos = _pos(owner=False)
    ev = _pm(pos).update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"] and pos.sl > 2950.0
    bm = _pos(mode="bot_manages")
    ev = _pm(bm).update_price("ETH", 3051.0)
    assert [e.action for e in ev] == ["TP1"] and "owner_ladder" not in bm.entry_reasons
    assert not _rows(sandbox)
