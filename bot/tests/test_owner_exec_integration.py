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
from tests.test_owner_plan_exec import _plan, _write_rows, _fills  # noqa: E402
from tests.test_owner_plans_any_coin import AnyBot, _tick, hl, sandbox  # noqa: E402,F401  (fixtures)

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
