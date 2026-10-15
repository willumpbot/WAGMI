"""Integration of OWNER_PLAN_ANY_COIN (claude/owner-plans-any-coin) + OWNER_LADDER_STYLE (claude/owner-ladder-style).

Laptop 178 section C: the mode/style interaction is only live with BOTH flags on. A LADDER plan on an EXTRA coin
requested as bot_manages is degraded to profits_only (any-coin), which is a restricted mode, so the owner's ladder
applies - while the same plan on a CORE coin stays bot_manages and the ladder does NOT apply (precedence, B3).
"""
import sys
from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from execution.position_manager import PositionManager  # noqa: E402
from tests.test_owner_plan_exec import _plan, _write_rows, _fills, _state  # noqa: E402
from tests.test_owner_plans_any_coin import AnyBot, _tick, hl, sandbox, state_file  # noqa: E402,F401  (fixtures)

ATR_D = 0.08


@pytest.fixture
def both_on(monkeypatch):
    monkeypatch.setenv("OWNER_PLAN_ANY_COIN", "true")
    monkeypatch.setenv("OWNER_LADDER_STYLE", "true")
    monkeypatch.delenv("OWNER_RUNNER_STYLE", raising=False)
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (ATR_D, "test"))


def test_ladder_plan_on_extra_coin_both_flags(sandbox, hl, both_on):
    p = _plan("lad", coin="SUI", etype="market", entry=3.05, stop=2.95, target=3.6, price_at_plan=3.05)
    p.update(exit_style="ladder", exit_mode="bot_manages")
    _write_rows(sandbox, p)
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, 3.05)
    pos = pm.positions["SUI"]
    er = pos.entry_reasons
    # style + mode (requested vs effective)
    assert er["exit_style"] == "ladder" and ope.owner_exit_style(pos) == "ladder"
    assert er["exit_mode_requested"] == "bot_manages" and er["exit_mode_effective"] == "profits_only"
    assert er["exit_mode_degraded"] is True and ope.owner_exit_mode(pos) == "profits_only"
    assert ope.ladder_applies(pos) and ope.ladder_live(pos)
    open_row = _fills(sandbox)[0]
    assert open_row["exit_style"] == "ladder" and open_row["exit_mode"] == "profits_only"
    assert open_row["exit_mode_requested"] == "bot_manages" and open_row["exit_mode_degraded"] is True

    # leg schedule: a quarter of the ORIGINAL qty at +0.5R / +0.75R / +1R, then the last quarter trails 1 ATR
    orig, entry = pos.qty, pos.entry
    r = entry - 2.95
    for k, m in ((1, 0.5), (2, 0.75), (3, 1.0)):
        _tick(bot, hl, round(entry + m * r + 0.001, 4))
        legs = [f for f in _fills(sandbox) if f["kind"] == "partial"]
        assert len(legs) == k, (k, legs)
        assert legs[-1]["reason"] == f"OWNER_LADDER_Q{k}" and legs[-1]["managed_by"] == f"ladder_q{k}"
        assert sum(l["qty"] for l in legs) == pytest.approx(k * orig / 4, abs=0.11)   # SUI lot = 0.1
        assert legs[-1]["exit_mode_degraded"] is True
    _tick(bot, hl, 3.40)
    assert pos.sl == pytest.approx(3.40 - ATR_D)              # trail armed after Q3, 1 x atr_at_fill
    _tick(bot, hl, 3.30)                                      # through the trail
    rows = _fills(sandbox)
    assert [f["kind"] for f in rows] == ["open", "partial", "partial", "partial", "final"]
    fin = rows[-1]
    assert fin["managed_by"] in ("ladder_trail", "stop") and fin["exit_style"] == "ladder"
    assert sum(f["qty"] for f in rows[1:]) == pytest.approx(orig)
    assert fin["total_r"] > 0 and "SUI" not in pm.positions


@pytest.mark.parametrize("lots,kinds,reasons", [
    (1, ["open", "final"], ["OWNER_LADDER_Q1"]),
    (2, ["open", "partial", "final"], ["OWNER_LADDER_Q1", "OWNER_LADDER_Q3"]),
    (3, ["open", "partial", "partial", "final"], ["OWNER_LADDER_Q1", "OWNER_LADDER_Q2", "OWNER_LADDER_Q3"]),
    (5, ["open", "partial", "partial", "partial", "final"],
     ["OWNER_LADDER_Q1", "OWNER_LADDER_Q2", "OWNER_LADDER_Q3", None]),
])
def test_ladder_on_coarse_lot_extra_coin(sandbox, hl, both_on, monkeypatch, state_file, lots, kinds, reasons):
    """szDecimals-0 coin (one lot = 1 unit) under the ladder, both flags on. A quarter below one lot snaps up to one
    lot; a step that would leave less than one lot closes the remainder and ends the ladder (no trail). Restart
    after the +0.75R tick: nothing re-fires, bookkeeping consistent, closes sum to the original size."""
    from core import owner_any_coin as oac
    from execution.auto_recovery import load_position_state
    monkeypatch.setattr(ope, "atr_at_fill", lambda bot, coin, ts: (0.5, "test"))
    p = _plan("cl", coin="BIGLOT", etype="market", entry=50.0, stop=48.0, target=60.0, price_at_plan=50.0,
              risk_usd=2.0 * lots)
    p.update(exit_style="ladder")
    _write_rows(sandbox, p)
    pm = PositionManager()
    bot = AnyBot(pm, {})
    _tick(bot, hl, BIGLOT=50)
    assert pm.positions["BIGLOT"].qty == lots and pm.positions["BIGLOT"].entry_reasons["exit_style"] == "ladder"
    _tick(bot, hl, BIGLOT=51.1)                                # +0.5R
    _tick(bot, hl, BIGLOT=51.6)                                # +0.75R
    n = len(_fills(sandbox))
    _tick(bot, hl, BIGLOT=51.65)                               # no re-fire
    assert len(_fills(sandbox)) == n

    # ---- restart: fresh objects, empty any-coin registry, state from disk ----
    pos0 = pm.positions.get("BIGLOT")
    oac._reset_for_tests()
    monkeypatch.setattr(oac, "_post", hl)
    pm2 = PositionManager()
    loaded = load_position_state(pm2, str(state_file)) if state_file.exists() else 0
    bot2 = AnyBot(pm2, {})
    if pos0 is None:
        assert loaded == 0
    else:
        back = pm2.positions["BIGLOT"]
        assert back.qty == pos0.qty
        assert back.entry_reasons["owner_ladder"]["steps_taken"] == pos0.entry_reasons["owner_ladder"]["steps_taken"]
    _tick(bot2, hl, BIGLOT=51.65)                              # still nothing re-fires after the restore
    assert len(_fills(sandbox)) == n
    for px in (52.1, 52.5, 52.6, 51.9):                        # +1R, trail to 52.0 (ATR 0.5), through it
        _tick(bot2, hl, BIGLOT=px)

    rows = _fills(sandbox)
    assert [r["kind"] for r in rows] == kinds
    for r, want in zip(rows[1:], reasons):
        if want:
            assert r["reason"] == want and r["managed_by"] == want.replace("OWNER_LADDER_Q", "ladder_q")
    assert sum(r["qty"] for r in rows[1:]) == pytest.approx(lots), "closes must sum to the original size"
    assert all(r["qty"] >= 1 for r in rows[1:]), "never a sub-lot leg"
    assert "BIGLOT" not in pm2.positions and _state(sandbox)["cl"]["status"] == "closed"
    if lots == 5:
        assert rows[-1]["managed_by"] in ("ladder_trail", "stop") and rows[-1]["qty"] == 2
    else:
        assert rows[-1]["reason"].startswith("OWNER_LADDER_Q")   # the step closed the remainder, no trail


def test_same_ladder_plan_on_core_coin_stays_bot_manages(sandbox, hl, both_on):
    """Precedence (B3): a CORE bot_manages plan is not degraded, so the ladder does not apply to it."""
    p = _plan("core", coin="ETH", etype="market", entry=3000.0, stop=2950.0, target=3200.0)
    p.update(exit_style="ladder", exit_mode="bot_manages")
    _write_rows(sandbox, p)
    pm = PositionManager()
    _tick(AnyBot(pm, {"ETH": 3000.0}), hl)
    pos = pm.positions["ETH"]
    assert ope.owner_exit_mode(pos) == "bot_manages" and not ope.ladder_applies(pos)
    assert "exit_mode_degraded" not in pos.entry_reasons and hl.calls == []
