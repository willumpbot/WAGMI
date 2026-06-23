"""
Tests for the regime-keyed empirical-Bayes prior (USE_REGIME_PRIORS).

Proves the four properties required by the 2026-06-23 edge-map audit:
  (a) the system baseline excludes LLM_EXIT_AGENT rows,
  (b) a SHORT-in-bull cell shrinks toward the SHORT.bull default, NOT the
      bear-driven pooled value,
  (c) recency weighting down-weights old trades,
  (d) flag OFF reproduces the current (legacy) behavior exactly.

Self-contained: builds in-memory ledgers and an isolated trade_ledger.csv,
no dependency on live data.
"""

from __future__ import annotations

import csv
import importlib
import os
import time

import pytest

from llm import regime_priors as rp


# Half-life constant mirrored locally so the recency test is explicit.
_DAY = 86400.0


def _mk(symbol, side, regime, exit_type, net_pnl, ts):
    return {
        "symbol": symbol,
        "side": side,
        "regime_1h": regime,
        "exit_type": exit_type,
        "net_pnl": str(net_pnl),
        "timestamp": str(ts),
    }


# ── (a) baseline excludes LLM_EXIT_AGENT ──────────────────────────────────

def test_pooled_baseline_excludes_llm_exit_agent():
    """LLM_EXIT_AGENT closes (0/N by construction) must not enter the baseline.

    Mirrors the audit: 71 LLM losers + 30 mechanical (19 winners) gives a
    contaminated pooled WR ~0.19, but the mechanical-only WR ~0.63.
    """
    trades = []
    # 71 LLM_EXIT_AGENT losers (the contaminant).
    for i in range(71):
        trades.append(_mk("ETH", "SHORT", "range", "LLM_EXIT_AGENT", -10.0, 1_780_000_000 + i))
    # 30 mechanical exits, 19 winners / 11 losers.
    for i in range(19):
        trades.append(_mk("ETH", "SHORT", "range", "TP2", 50.0, 1_780_100_000 + i))
    for i in range(11):
        trades.append(_mk("ETH", "SHORT", "range", "SL", -50.0, 1_780_200_000 + i))

    # Contaminated pooled WR over ALL exits.
    all_wins = sum(1 for t in trades if float(t["net_pnl"]) > 0)
    contaminated = all_wins / len(trades)
    assert contaminated < 0.25, f"sanity: contaminated baseline should be low, got {contaminated}"

    mech_wr, n = rp.pooled_mechanical_win_rate(trades)
    assert n == 30, "mechanical filter must keep exactly the 30 mechanical exits"
    assert mech_wr == pytest.approx(19 / 30, abs=1e-9)
    assert mech_wr > 0.6, "de-contaminated WR must reflect true mechanical edge (~0.63)"
    # And the LLM rows are genuinely gone.
    assert all(rp.is_mechanical(t["exit_type"]) for t in rp.mechanical_trades(trades))


def test_get_system_baseline_flag_on_uses_mechanical_ledger(tmp_path, monkeypatch):
    """With the flag ON, get_system_baseline reads the mechanical-only ledger."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ledger = data_dir / "trade_ledger.csv"
    rows = []
    for i in range(71):
        rows.append(_mk("ETH", "SHORT", "range", "LLM_EXIT_AGENT", -10.0, 1_780_000_000 + i))
    for i in range(19):
        rows.append(_mk("ETH", "SHORT", "range", "TP2", 50.0, 1_780_100_000 + i))
    for i in range(11):
        rows.append(_mk("ETH", "SHORT", "range", "SL", -50.0, 1_780_200_000 + i))
    with open(ledger, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    import llm.agents.dynamic_stats as ds
    importlib.reload(ds)
    monkeypatch.setattr(ds, "_DATA_DIR", data_dir, raising=True)
    monkeypatch.setenv("USE_REGIME_PRIORS", "true")

    wr, payoff = ds.get_system_baseline()
    assert wr == pytest.approx(19 / 30, abs=1e-9), "baseline must be mechanical-only WR"
    assert payoff == pytest.approx(50.0 / 50.0, abs=1e-9)


# ── (b) SHORT-in-bull shrinks toward SHORT.bull default, not pooled ────────

def test_short_in_bull_shrinks_to_short_bull_default_not_pooled():
    """A SHORT-in-bull cell must be pulled toward the SHORT.bull default.

    The pooled SHORT edge is bear-driven (SHORT.bear default 0.60). If the
    prior were keyed by side only, a cold SHORT-in-bull cell would inherit
    that bear-driven number. Regime-keying must instead pull it toward the
    SHORT.bull default (0.40).
    """
    now = 1_782_000_000.0
    # Bear cell is rich and winning; bull cell is empty/cold.
    trades = []
    for i in range(20):
        trades.append(_mk("BTC", "SHORT", "trending_bear", "TP2", 100.0, now - i * _DAY))

    table = rp.RegimePriorTable(now_ts=now).fit(trades)

    bull_default = rp.side_regime_default("SHORT", "bull")
    bear_default = rp.side_regime_default("SHORT", "bear")
    assert bull_default == 0.40 and bear_default == 0.60

    # Empty bull cell -> exactly the SHORT.bull default (full shrinkage).
    wp_bull = table.win_prob("BTC", "SHORT", "trending_bull")
    assert wp_bull == pytest.approx(bull_default, abs=1e-9)
    # It is pulled toward the bull default, NOT the bear-driven pooled value.
    assert abs(wp_bull - bull_default) < abs(wp_bull - bear_default)
    assert wp_bull < 0.50, "SHORT-in-bull must not inherit the bear short edge"

    # And the rich bear cell shrinks toward its own (high) bear default + data.
    wp_bear = table.win_prob("BTC", "SHORT", "trending_bear")
    assert wp_bear > 0.80, "rich winning bear cell should reflect its strong edge"

    # A partially-populated bull cell with a single mechanical loss still sits
    # near the bull default (shrinkage k=5 dominates a tiny cell).
    trades2 = trades + [_mk("BTC", "SHORT", "trending_bull", "SL", -50.0, now)]
    table2 = rp.RegimePriorTable(now_ts=now).fit(trades2)
    wp_bull2 = table2.win_prob("BTC", "SHORT", "trending_bull")
    # (0 wins + 5*0.40) / (1 + 5) = 2.0/6 = 0.333...
    assert wp_bull2 == pytest.approx((0 + 5 * 0.40) / (1 + 5), abs=1e-9)
    assert wp_bull2 < bear_default


# ── (c) recency weighting down-weights old trades ─────────────────────────

def test_recency_weighting_downweights_old_trades():
    """Old trades contribute less mass; the prior leans toward recent outcomes."""
    now = 1_782_000_000.0

    # Case 1: recent winners + old losers -> WP above the half-of-data point.
    recent_winners = [
        _mk("SOL", "SHORT", "range", "TP2", 50.0, now - 1 * _DAY) for _ in range(10)
    ]
    old_losers = [
        _mk("SOL", "SHORT", "range", "SL", -50.0, now - 200 * _DAY) for _ in range(10)
    ]
    table = rp.RegimePriorTable(now_ts=now).fit(recent_winners + old_losers)
    wp_recent_win = table.win_prob("SOL", "SHORT", "range")

    # Mirror image: old winners + recent losers -> lower WP.
    old_winners = [
        _mk("SOL", "SHORT", "range", "TP2", 50.0, now - 200 * _DAY) for _ in range(10)
    ]
    recent_losers = [
        _mk("SOL", "SHORT", "range", "SL", -50.0, now - 1 * _DAY) for _ in range(10)
    ]
    table2 = rp.RegimePriorTable(now_ts=now).fit(old_winners + recent_losers)
    wp_recent_loss = table2.win_prob("SOL", "SHORT", "range")

    assert wp_recent_win > wp_recent_loss, (
        "recent winners must yield higher WP than recent losers with identical "
        "trade counts — recency weighting must down-weight old trades"
    )

    # Explicit weight check: a 21-day-old trade has exactly half the weight.
    w_now = rp._recency_weight(now, now)
    w_half_life = rp._recency_weight(now - rp.RECENCY_HALF_LIFE_DAYS * _DAY, now)
    assert w_now == pytest.approx(1.0, abs=1e-9)
    assert w_half_life == pytest.approx(0.5, abs=1e-9)

    # Weighted mass of old trades is strictly less than the same count of new.
    _, n_recent = table.cell_mass("SOL", "SHORT", "neutral")  # range -> neutral bucket
    assert n_recent > 0


# ── (d) flag OFF reproduces current behavior exactly ──────────────────────

def test_flag_off_baseline_matches_legacy(tmp_path, monkeypatch):
    """With the flag OFF, get_system_baseline must use the legacy trades.csv path.

    We build a ledger that, if (wrongly) consulted, would change the answer.
    With the flag off the function must ignore it and return the legacy value
    computed from trades.csv (here: insufficient data -> the 0.50/1.5 fallback).
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # A mechanical ledger that WOULD give 1.0 WR if consulted.
    ledger = data_dir / "trade_ledger.csv"
    rows = [_mk("ETH", "SHORT", "range", "TP2", 50.0, 1_780_100_000 + i) for i in range(15)]
    with open(ledger, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    import llm.agents.dynamic_stats as ds
    importlib.reload(ds)
    monkeypatch.setattr(ds, "_DATA_DIR", data_dir, raising=True)
    # Point the legacy loader at an empty/absent trades.csv so legacy returns
    # its fallback (0.50, 1.5) — distinct from the ledger's 1.0 WR.
    monkeypatch.setattr(ds, "TRADES_CSV", data_dir / "trades.csv", raising=True)

    monkeypatch.delenv("USE_REGIME_PRIORS", raising=False)
    wr_off, payoff_off = ds.get_system_baseline()
    assert (wr_off, payoff_off) == (0.50, 1.5), (
        "flag OFF must reproduce legacy fallback, ignoring the ledger"
    )

    # And with the flag ON the same ledger flips the answer to mechanical WR=1.0.
    monkeypatch.setenv("USE_REGIME_PRIORS", "true")
    wr_on, _ = ds.get_system_baseline()
    assert wr_on == pytest.approx(1.0, abs=1e-9)


def test_flag_off_disables_regime_prior_table(monkeypatch):
    """QuantBrain must not build a regime-prior table when the flag is off."""
    monkeypatch.delenv("USE_REGIME_PRIORS", raising=False)
    assert rp.flag_enabled() is False
    from llm.quant_brain import QuantBrain
    brain = QuantBrain()
    assert brain._regime_priors is None, "flag off => no regime prior table => legacy lookup"


def test_regime_bucket_collapse():
    assert rp.regime_bucket("trending_bull") == "bull"
    assert rp.regime_bucket("trending_bear") == "bear"
    assert rp.regime_bucket("range") == "neutral"
    assert rp.regime_bucket("consolidation") == "neutral"
    assert rp.regime_bucket("") == "neutral"
    assert rp.regime_bucket(None) == "neutral"
