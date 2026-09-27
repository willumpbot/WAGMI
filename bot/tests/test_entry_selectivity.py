"""Tests for core/entry_selectivity.py — the ENTRY SELECTIVITY gates.

The headline test (test_counterfactual_reproduction) REPLAYS the bot's own
historical trades (data/trades.csv) through evaluate_entry in "true" mode and
proves the module reproduces the adversarially-verified 2026-07-27 finding:
blocking solo / loss-streak / neg-EV entries (while KEEPING exploration) skips
a set dominated by losers and keeps a set with a materially higher win-rate.

Run: cd bot && python -m pytest tests/test_entry_selectivity.py -q
"""
import os
import csv
import json
import importlib

import pytest

import core.entry_selectivity as es


_HERE = os.path.dirname(os.path.abspath(__file__))
_TRADES = os.path.join(os.path.dirname(_HERE), "data", "trades.csv")


# ─────────────────────────── env / cache helpers ────────────────────────────

@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """Force a fresh living-value recompute for every test (mtime/TTL cache is
    process-global)."""
    es._cache["computed_at"] = 0.0
    es._cache["ledger_mtime"] = -1.0
    es._cache["trades_mtime"] = -1.0
    yield


def _set_mode(monkeypatch, mode):
    monkeypatch.setenv("ENTRY_SELECTIVITY", mode)


# ─────────────────────────── counterfactual replay ──────────────────────────

def _load_replay_records():
    """Historical trades from data/trades.csv, decorated exactly as the live
    caller would supply evaluate_entry's inputs:
      - num_agree   <- entry_reasons.num_agree (else len(strategies_agree))
      - ev_per_dollar <- entry_reasons.ev_per_dollar
      - is_exploration <- entry_type == EXPLORATION
      - loss_streak  <- consecutive-loss count active at entry, computed from
                        the epoch's own close order (trades.csv is close-ordered
                        and carries the NET, de-leveraged pnl).
    """
    recs = []
    streak = 0
    with open(_TRADES, newline="", encoding="utf-8", errors="ignore") as f:
        for r in csv.DictReader(f):
            try:
                er = json.loads(r.get("entry_reasons") or "{}")
            except (ValueError, TypeError):
                er = {}
            if not isinstance(er, dict):
                er = {}
            try:
                pnl = float(r.get("pnl") or 0)
            except (ValueError, TypeError):
                continue
            ev = er.get("ev_per_dollar")
            try:
                ev = float(ev) if ev is not None else None
            except (ValueError, TypeError):
                ev = None
            recs.append({
                "pnl": pnl,
                "num_agree": es._num_agree_from_reasons(er),
                "ev": ev,
                "is_exploration": es._is_exploration_row(r, er),
                "loss_streak": streak,
            })
            streak = 0 if pnl > 0 else streak + 1
    return recs


def _wr(group):
    if not group:
        return 0.0
    return 100.0 * sum(1 for x in group if x["pnl"] > 0) / len(group)


def _net(group):
    return sum(x["pnl"] for x in group)


def test_counterfactual_reproduction(monkeypatch, capsys):
    """Replay trades.csv through the real gate (true mode) and prove the kept
    set has a materially higher WR than the skipped set, avoided loss >> forgone
    wins, and removing the skipped trades flips the epoch strongly positive."""
    _set_mode(monkeypatch, "true")
    recs = _load_replay_records()
    assert len(recs) > 100, "expected a substantial trade history to replay"

    kept, skipped = [], []
    for x in recs:
        block, reasons, mode = es.evaluate_entry(
            num_agree=x["num_agree"],
            ev_per_dollar=x["ev"],
            loss_streak=x["loss_streak"],
            is_exploration=x["is_exploration"],
        )
        assert mode == "true"
        (skipped if block else kept).append(x)

    kept_n, skip_n = len(kept), len(skipped)
    kept_wr, skip_wr = _wr(kept), _wr(skipped)
    kept_net, skip_net = _net(kept), _net(skipped)
    all_net = _net(recs)
    forgone_wins = sum(x["pnl"] for x in skipped if x["pnl"] > 0)
    avoided_loss = -skip_net  # positive number = net dollars the skip removed

    # Report the exact numbers (visible with -s / on failure).
    print("\n[ENTRY-SELECTIVITY COUNTERFACTUAL]")
    print("  N* (loss-streak) = %s | solo gate active = %s"
          % (es.get_streak_threshold(), es.get_solo_gate().get("active")))
    print("  ALL    n=%d  net=%.2f" % (len(recs), all_net))
    print("  KEPT   n=%d  WR=%.1f%%  net=%.2f" % (kept_n, kept_wr, kept_net))
    print("  SKIP   n=%d  WR=%.1f%%  net=%.2f" % (skip_n, skip_wr, skip_net))
    print("  avoided loss=%.2f  forgone wins=%.2f" % (avoided_loss, forgone_wins))

    # 1. Both sets are non-trivial.
    assert kept_n > 50 and skip_n > 30

    # 2. Kept WR is materially higher than skipped WR (wide margin).
    assert kept_wr - skip_wr > 20.0, (kept_wr, skip_wr)

    # 3. The skipped set is dominated by losers (net strongly negative) and its
    #    avoided loss dwarfs the wins we forgo by skipping it.
    assert skip_net < -300.0
    assert avoided_loss > 3.0 * forgone_wins

    # 4. Removing the skipped trades flips the epoch strongly positive: the kept
    #    subset nets far more than trading everything.
    assert kept_net > all_net + 300.0
    assert kept_net > 300.0

    # 5. Exploration trades are all in the kept set (never skipped).
    assert all(not x["is_exploration"] for x in skipped)
    n_expl = sum(1 for x in recs if x["is_exploration"])
    n_expl_kept = sum(1 for x in kept if x["is_exploration"])
    assert n_expl > 0 and n_expl_kept == n_expl  # every exploration trade kept


# ─────────────────────────── mode contracts ─────────────────────────────────

def test_off_mode_never_blocks(monkeypatch):
    """off (default) is byte-equivalent: always (False, [], 'off'), even on a
    dead-obvious block case."""
    _set_mode(monkeypatch, "off")
    block, reasons, mode = es.evaluate_entry(
        num_agree=1, ev_per_dollar=-5.0, loss_streak=99, is_exploration=False)
    assert block is False
    assert reasons == []
    assert mode == "off"


def test_off_is_default(monkeypatch):
    monkeypatch.delenv("ENTRY_SELECTIVITY", raising=False)
    assert es.mode() == "off"
    block, reasons, mode = es.evaluate_entry(
        num_agree=1, ev_per_dollar=-1.0, loss_streak=50, is_exploration=False)
    assert block is False and mode == "off"


def test_exploration_always_exempt(monkeypatch):
    """Exploration is exempt in every enforcing mode, even when every gate would
    otherwise fire."""
    for mode_name in ("shadow", "true"):
        _set_mode(monkeypatch, mode_name)
        block, reasons, mode = es.evaluate_entry(
            num_agree=1, ev_per_dollar=-9.0, loss_streak=99, is_exploration=True)
        assert block is False, mode_name
        assert reasons == ["exploration-exempt"], mode_name
        assert mode == mode_name


def test_shadow_never_blocks_but_reports(monkeypatch):
    """shadow computes would-block reasons but never blocks."""
    _set_mode(monkeypatch, "shadow")
    block, reasons, mode = es.evaluate_entry(
        num_agree=1, ev_per_dollar=-2.0, loss_streak=99, is_exploration=False)
    assert block is False
    assert mode == "shadow"
    assert len(reasons) >= 1  # at least neg-EV should be flagged


# ─────────────────────────── fail-open ──────────────────────────────────────

def test_fail_open_on_bad_input(monkeypatch):
    """Garbage inputs must never raise and never block (fail-open)."""
    _set_mode(monkeypatch, "true")
    block, reasons, mode = es.evaluate_entry(
        num_agree="not-an-int", ev_per_dollar="nope",
        loss_streak=object(), is_exploration=False)
    assert block is False  # unparseable inputs simply don't trip gates
    # And a hard failure inside the gate still fails open:
    _set_mode(monkeypatch, "true")
    monkeypatch.setattr(es, "_ensure_fresh",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    block, reasons, mode = es.evaluate_entry(
        num_agree=1, ev_per_dollar=-1.0, loss_streak=99, is_exploration=False)
    assert block is False and reasons == []


# ─────────────────────────── each gate fires ────────────────────────────────

def test_neg_ev_gate_true_mode_blocks(monkeypatch):
    """NEG-EV with ENTRY_SELECTIVITY_NEGEV=true: block when ev_per_dollar < 0."""
    _set_mode(monkeypatch, "true")
    monkeypatch.setenv("ENTRY_SELECTIVITY_NEGEV", "true")
    block, reasons, mode = es.evaluate_entry(
        num_agree=3, ev_per_dollar=-0.01, loss_streak=0, is_exploration=False)
    assert block is True
    assert any(r.startswith("neg_ev(") for r in reasons)
    # positive EV, healthy confluence, no streak -> no block
    block2, reasons2, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=0.5, loss_streak=0, is_exploration=False)
    assert block2 is False and reasons2 == []


def test_neg_ev_gate_default_shadow(monkeypatch):
    """NEG-EV defaults to SHADOW (predicted_ev is noise-grade): records a
    neg_ev_shadow reason for observability but never contributes to a block, while
    the proven legs still enforce under ENTRY_SELECTIVITY=true."""
    _set_mode(monkeypatch, "true")
    monkeypatch.delenv("ENTRY_SELECTIVITY_NEGEV", raising=False)  # default -> shadow
    assert es.entry_selectivity_negev_mode() == "shadow"
    block, reasons, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=-0.01, loss_streak=0, is_exploration=False)
    assert block is False, "neg-EV must NOT block in default shadow mode"
    assert any(r.startswith("neg_ev_shadow(") for r in reasons), "shadow reason recorded"
    assert not any(r.startswith("neg_ev(") for r in reasons), "no hard neg_ev reason"
    # off mode: neg-EV leg not evaluated at all
    monkeypatch.setenv("ENTRY_SELECTIVITY_NEGEV", "off")
    block2, reasons2, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=-0.01, loss_streak=0, is_exploration=False)
    assert block2 is False and reasons2 == []


def test_solo_gate_fires(monkeypatch):
    """CONFLUENCE/SOLO: on this ledger the solo bucket is far below breakeven, so
    a num_agree<2 entry blocks; num_agree>=2 does not (solo-only case)."""
    _set_mode(monkeypatch, "true")
    assert es.get_solo_gate().get("active") is True, "fixture data must have an active solo gate"
    block, reasons, _ = es.evaluate_entry(
        num_agree=1, ev_per_dollar=None, loss_streak=0, is_exploration=False)
    assert block is True
    assert any(r.startswith("solo_below_breakeven") for r in reasons)
    # 2-strategy agreement with no other flag -> not blocked
    block2, reasons2, _ = es.evaluate_entry(
        num_agree=2, ev_per_dollar=None, loss_streak=0, is_exploration=False)
    assert block2 is False and reasons2 == []


def test_loss_streak_gate_off_by_default(monkeypatch):
    """LOSS-STREAK gate is REMOVED by default (owner 2026-07-29 "no loss gate"):
    even a large loss streak with healthy confluence does NOT block."""
    _set_mode(monkeypatch, "true")
    monkeypatch.delenv("ENTRY_SELECTIVITY_STREAK", raising=False)  # default off
    assert es.loss_streak_gate_enabled() is False
    n_star = es.get_streak_threshold() or 3
    block, reasons, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=None, loss_streak=n_star + 5, is_exploration=False)
    assert block is False
    assert not any(r.startswith("loss_streak>=N*") for r in reasons)


def test_trend_direction_gate_short_no_tailwind(monkeypatch):
    """TREND_DIRECTION_GATE (data-driven 2026-07-30): SHORTS without downside momentum
    (sym_d24h > T_down=-3%) are flagged; shadow (default) records but never blocks;
    deep-down shorts pass; mode=true enforces; longs unaffected by the short leg."""
    _set_mode(monkeypatch, "true")
    monkeypatch.delenv("TREND_DIRECTION_GATE", raising=False)  # default -> shadow
    assert es.trend_direction_gate_mode() == "shadow"
    b, r, _ = es.evaluate_entry(num_agree=3, ev_per_dollar=0.1, loss_streak=0,
                                is_exploration=False, side="SELL", sym_d24h=-1.5)
    assert b is False and any(x.startswith("short_no_tailwind_shadow(") for x in r)
    # deep-down short (d24h <= -3): has tailwind, no flag
    _, r2, _ = es.evaluate_entry(num_agree=3, ev_per_dollar=0.1, loss_streak=0,
                                 is_exploration=False, side="SELL", sym_d24h=-5.0)
    assert not any("tailwind" in x for x in r2)
    # mode=true enforces the block on the shallow-dip short
    monkeypatch.setenv("TREND_DIRECTION_GATE", "true")
    b3, r3, _ = es.evaluate_entry(num_agree=3, ev_per_dollar=0.1, loss_streak=0,
                                  is_exploration=False, side="SELL", sym_d24h=-1.5)
    assert b3 is True and any(x.startswith("short_no_tailwind(") for x in r3)
    # LONG unaffected by the short-only leg
    _, r4, _ = es.evaluate_entry(num_agree=3, ev_per_dollar=0.1, loss_streak=0,
                                 is_exploration=False, side="BUY", sym_d24h=2.0)
    assert not any("tailwind" in x for x in r4)


def test_loss_streak_gate_fires_only_when_enabled(monkeypatch):
    """The leg is preserved + reversible: with ENTRY_SELECTIVITY_STREAK=true it
    blocks at loss_streak >= N* and passes below it (same behavior as before)."""
    _set_mode(monkeypatch, "true")
    monkeypatch.setenv("ENTRY_SELECTIVITY_STREAK", "true")
    n_star = es.get_streak_threshold()
    assert n_star is not None and n_star >= 1
    block, reasons, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=None, loss_streak=n_star, is_exploration=False)
    assert block is True
    assert any(r.startswith("loss_streak>=N*") for r in reasons)
    block2, reasons2, _ = es.evaluate_entry(
        num_agree=3, ev_per_dollar=None, loss_streak=n_star - 1, is_exploration=False)
    assert block2 is False and reasons2 == []


def test_living_values_are_derived_not_hardcoded():
    """The thresholds must come from the data (n>=13), not constants."""
    solo = es.get_solo_gate()
    assert solo.get("n", 0) >= 13
    assert solo.get("breakeven_wr") is not None
    n_star = es.get_streak_threshold()
    # N* is derived; on the shipped fixture it is a small positive int.
    assert n_star is None or n_star >= 1


def test_module_import_side_effect_free():
    """Importing the module must not require any env or perform blocking work."""
    importlib.reload(es)
    assert callable(es.evaluate_entry)
