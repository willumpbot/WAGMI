"""
Tests for the LEARNING-INPUT DUST FLOOR (LEARNING_INPUT_FLOOR, default OFF).

Adversarially-verified context (2026-07-24): 181 of 250 trade_ledger.csv rows
(72%) are DUST — tiny early-epoch positions (median corrected base notional
~$144 vs ~$1078 for real trades) whose recorded round-trip fees are < $0.50.
With dust counted as evidence, 9 of 10 (symbol,side) cells pass the n>=13
living-values gate ONLY because of dust, Kelly factor priors are built on
56/72 dust inputs, and the 77.5 breakeven confidence floor evaporates on
real-only evidence.

The floor treats rows with fees < live_edge.DUST_FEE_FLOOR as non-evidence in:
  - live_edge._recompute() n>=13 counts / side-mults / symbol-mults
  - live_edge._recompute() breakeven confidence-floor scan
  - kelly_engine._load_ledger_factor_trades() factor priors

Flag OFF (default) must be byte-identical to pre-existing behavior. Cells
that drop below n>=13 real-only must revert to the safe neutral (None ->
caller falls back to mult 1.0 / no edge / non-lowering floor fallback).

All ledger access goes through a temp CSV — never real ledger data.
"""
import csv
import os

import pytest

from feedback import live_edge
from feedback.kelly_engine import _load_ledger_factor_trades

HEADER = [
    "trade_id", "timestamp", "symbol", "side", "contributing_factors",
    "confidence_score", "entry_price", "fees", "net_pnl", "running_equity",
]


def _write_ledger(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _row(i, symbol, side, fees, pnl, conf=80.0, factors="confidence_scorer"):
    return {
        "trade_id": f"T{i}",
        "timestamp": "2026-07-20T00:00:00+00:00",
        "symbol": symbol,
        "side": side,
        "contributing_factors": factors,
        "confidence_score": conf,
        "entry_price": 2000.0,  # not in _TEST_ENTRY_PRICES
        "fees": fees,
        "net_pnl": pnl,
        "running_equity": 5000.0,
    }


@pytest.fixture()
def dusty_ledger(tmp_path, monkeypatch):
    """13 real BTC_SELL winners; HYPE_SELL = 2 real + 11 dust rows.

    Flag OFF: both cells reach n>=13. Flag ON: only BTC_SELL survives.
    Dust rows carry conf>=77.5 so the breakeven scan's dust-dependence is
    testable too.
    """
    rows = []
    i = 0
    for _ in range(13):  # real BTC_SELL: fees $0.9, +$10 each
        rows.append(_row(i, "BTC", "SELL", 0.9, 10.0, conf=80.0)); i += 1
    for _ in range(2):   # real HYPE_SELL
        rows.append(_row(i, "HYPE", "SELL", 0.9, -20.0, conf=60.0)); i += 1
    for _ in range(11):  # dust HYPE_SELL: fees $0.1, tiny positive pnl,
        rows.append(_row(i, "HYPE", "SELL", 0.1, 0.5, conf=60.0)); i += 1
    path = tmp_path / "trade_ledger.csv"
    _write_ledger(path, rows)
    monkeypatch.setattr(live_edge, "_LEDGER", str(path))
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LEARNING_INPUT_FLOOR", raising=False)
    monkeypatch.delenv("LIVE_EDGE_WINDOW_DAYS", raising=False)
    yield


# ---------------------------------------------------------------------------
# Flag plumbing
# ---------------------------------------------------------------------------

class TestFlag:
    def test_defaults_off(self):
        assert live_edge.learning_input_floor_enabled() is False

    def test_truthy_values(self, monkeypatch):
        for v in ("1", "true", "True", "TRUE", "yes", " yes "):
            monkeypatch.setenv("LEARNING_INPUT_FLOOR", v)
            assert live_edge.learning_input_floor_enabled() is True

    def test_falsy_values(self, monkeypatch):
        for v in ("0", "false", "no", ""):
            monkeypatch.setenv("LEARNING_INPUT_FLOOR", v)
            assert live_edge.learning_input_floor_enabled() is False

    def test_floor_constant(self):
        assert live_edge.DUST_FEE_FLOOR == 0.5


# ---------------------------------------------------------------------------
# live_edge._recompute: side-mults / n>=13 / breakeven scan
# ---------------------------------------------------------------------------

class TestLiveEdgeRecompute:
    def test_flag_off_dust_counts_as_before(self, dusty_ledger):
        mult, meta, symbol_mult, symbol_meta, be, _, _ = live_edge._recompute()
        assert ("BTC", "SELL") in mult
        assert ("HYPE", "SELL") in mult          # dust-supported cell present
        assert meta[("HYPE", "SELL")]["n"] == 13
        assert be is not None                    # dust-supported floor found

    def test_flag_on_dust_excluded(self, dusty_ledger, monkeypatch):
        monkeypatch.setenv("LEARNING_INPUT_FLOOR", "true")
        mult, meta, symbol_mult, symbol_meta, be, _, _ = live_edge._recompute()
        # Real cell survives, with the same evidence as before (13 real rows).
        assert ("BTC", "SELL") in mult
        assert meta[("BTC", "SELL")]["n"] == 13
        # Dust-supported cell drops below n>=13 -> absent -> caller neutral.
        assert ("HYPE", "SELL") not in mult
        assert ("HYPE", "SELL") not in meta
        assert "HYPE" not in symbol_mult
        # Breakeven scan: only the 13 real BTC rows (conf 80, positive) remain
        # -> a floor still exists here at <=80; the dust conf-60 rows no
        # longer contribute evidence at any threshold.
        assert be is not None and be <= 80.0

    def test_flag_on_boundary_fee_is_kept(self, tmp_path, monkeypatch):
        """fees == DUST_FEE_FLOOR exactly is real evidence (>= floor)."""
        rows = [_row(i, "ETH", "SELL", 0.5, 5.0) for i in range(13)]
        path = tmp_path / "ledger_boundary.csv"
        _write_ledger(path, rows)
        monkeypatch.setattr(live_edge, "_LEDGER", str(path))
        monkeypatch.setenv("LEARNING_INPUT_FLOOR", "true")
        mult, meta, _, _, _, _, _ = live_edge._recompute()
        assert meta[("ETH", "SELL")]["n"] == 13

    def test_flag_on_missing_fees_treated_as_dust(self, tmp_path, monkeypatch):
        """A row that can't prove it paid fees can't be evidence (fail-closed)."""
        rows = [_row(i, "ETH", "SELL", "", 5.0) for i in range(13)]
        path = tmp_path / "ledger_nofees.csv"
        _write_ledger(path, rows)
        monkeypatch.setattr(live_edge, "_LEDGER", str(path))
        monkeypatch.setenv("LEARNING_INPUT_FLOOR", "true")
        mult, meta, _, _, be, _, _ = live_edge._recompute()
        assert mult == {} and meta == {} and be is None

    def test_flag_off_missing_fees_still_counts(self, tmp_path, monkeypatch):
        rows = [_row(i, "ETH", "SELL", "", 5.0) for i in range(13)]
        path = tmp_path / "ledger_nofees2.csv"
        _write_ledger(path, rows)
        monkeypatch.setattr(live_edge, "_LEDGER", str(path))
        mult, meta, _, _, _, _, _ = live_edge._recompute()
        assert meta[("ETH", "SELL")]["n"] == 13


# ---------------------------------------------------------------------------
# kelly_engine._load_ledger_factor_trades: factor priors
# ---------------------------------------------------------------------------

class TestKellyLedgerLoader:
    def test_flag_off_dust_counts_as_before(self, dusty_ledger):
        trades = _load_ledger_factor_trades(dusty_ledger)
        assert len(trades["confidence_scorer"]) == 26  # 13 + 2 + 11

    def test_flag_on_dust_excluded(self, dusty_ledger, monkeypatch):
        monkeypatch.setenv("LEARNING_INPUT_FLOOR", "true")
        trades = _load_ledger_factor_trades(dusty_ledger)
        assert len(trades["confidence_scorer"]) == 15  # 13 + 2 real only
        # The surviving records are the real ones (|pnl| large, not the $0.5 dust)
        assert all(abs(t["pnl_pct"]) >= 0.2 for t in trades["confidence_scorer"])


# ---------------------------------------------------------------------------
# SIDE_LEVEL_EDGE: living side-level mult fallback (data-derived, n>=13)
# ---------------------------------------------------------------------------

@pytest.fixture()
def side_ledger(tmp_path, monkeypatch):
    """16 real LONG losers + 16 real SHORT winners across 4 symbols.

    No single (symbol,side) cell reaches n>=13 (each is n=4), but the SIDE
    aggregate does (BUY n=16, SELL n=16). Exercises the side-level fallback.
    """
    rows = []
    i = 0
    for sym in ("BTC", "ETH", "SOL", "XRP"):
        for _ in range(4):
            rows.append(_row(i, sym, "LONG", 0.9, -20.0)); i += 1   # avg -20 -> mult floor 0.25
            rows.append(_row(i, sym, "SELL", 0.9, 15.0)); i += 1    # avg +15 -> mult cap 1.5
    path = tmp_path / "trade_ledger.csv"
    _write_ledger(path, rows)
    monkeypatch.setattr(live_edge, "_LEDGER", str(path))
    # force cache refresh against the temp ledger
    live_edge._cache["ledger_mtime"] = -1.0
    return str(path)


class TestSideLevelEdge:
    def test_flag_defaults_off(self):
        assert live_edge.side_level_edge_enabled() is False

    def test_side_mults_are_data_derived(self, side_ledger):
        _, _, _, _, _, side_mult, side_meta = live_edge._recompute()
        # values COMPUTED from real avg_pnl via _pnl_to_mult, not hardcoded
        assert side_meta["BUY"]["n"] == 16 and side_meta["SELL"]["n"] == 16
        assert side_mult["BUY"] == live_edge._pnl_to_mult(-20.0)   # 0.25 floor
        assert side_mult["SELL"] == live_edge._pnl_to_mult(15.0)   # 1.5 cap
        assert side_mult["BUY"] < 1.0 < side_mult["SELL"]

    def test_fallback_off_stays_neutral(self, side_ledger, monkeypatch):
        monkeypatch.delenv("SIDE_LEVEL_EDGE", raising=False)
        # no per-cell n>=13 -> None (current behavior, no side fallback)
        assert live_edge.get_side_mult("BTC", "LONG") is None
        assert live_edge.get_side_mult("ETH", "SELL") is None

    def test_fallback_on_uses_living_side_mult(self, side_ledger, monkeypatch):
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        live_edge._cache["ledger_mtime"] = -1.0  # refresh
        assert live_edge.get_side_mult("BTC", "LONG") == live_edge._pnl_to_mult(-20.0)
        assert live_edge.get_side_mult("SOL", "LONG") == live_edge._pnl_to_mult(-20.0)
        assert live_edge.get_side_mult("XRP", "SELL") == live_edge._pnl_to_mult(15.0)

    def test_specific_cell_still_wins_over_side(self, tmp_path, monkeypatch):
        # a cell WITH n>=13 keeps its own mult even when the side fallback is on
        rows = [_row(i, "BTC", "SELL", 0.9, 5.0) for i in range(13)]
        rows += [_row(100 + i, "ETH", "LONG", 0.9, -20.0) for i in range(16)]
        path = tmp_path / "trade_ledger.csv"
        _write_ledger(path, rows)
        monkeypatch.setattr(live_edge, "_LEDGER", str(path))
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        live_edge._cache["ledger_mtime"] = -1.0
        assert live_edge.get_side_mult("BTC", "SELL") == live_edge._pnl_to_mult(5.0)  # own cell


class TestSideFallbackNoBoost:
    """SIDE_FALLBACK_NO_BOOST: the side-level fallback may CUT but never BOOST a
    (symbol,side) cell that has no own n>=13 evidence (the SELL 1.5x aggregate is
    stale June outliers)."""

    def test_mode_defaults_to_shadow(self, monkeypatch):
        monkeypatch.delenv("SIDE_FALLBACK_NO_BOOST", raising=False)
        assert live_edge.side_fallback_mode() == "shadow"

    def test_shadow_leaves_sizing_unchanged(self, side_ledger, monkeypatch):
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        monkeypatch.delenv("SIDE_FALLBACK_NO_BOOST", raising=False)  # -> shadow
        live_edge._cache["ledger_mtime"] = -1.0
        # boost fallback and cut fallback BOTH returned unchanged in shadow
        assert live_edge.get_side_mult("XRP", "SELL") == live_edge._pnl_to_mult(15.0)   # 1.5
        assert live_edge.get_side_mult("BTC", "LONG") == live_edge._pnl_to_mult(-20.0)  # 0.25

    def test_true_clamps_boost_but_preserves_cut(self, side_ledger, monkeypatch):
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        monkeypatch.setenv("SIDE_FALLBACK_NO_BOOST", "true")
        live_edge._cache["ledger_mtime"] = -1.0
        # evidence-less SELL cells: boost clamped to 1.0 (no free 1.5x)
        assert live_edge.get_side_mult("XRP", "SELL") == 1.0
        assert live_edge.get_side_mult("SOL", "SELL") == 1.0
        # evidence-less LONG cells: cut PRESERVED (clamp only caps the top)
        assert live_edge.get_side_mult("BTC", "LONG") == live_edge._pnl_to_mult(-20.0)  # 0.25

    def test_off_is_legacy_boost(self, side_ledger, monkeypatch):
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        monkeypatch.setenv("SIDE_FALLBACK_NO_BOOST", "off")
        live_edge._cache["ledger_mtime"] = -1.0
        assert live_edge.get_side_mult("XRP", "SELL") == live_edge._pnl_to_mult(15.0)   # 1.5

    def test_own_evidence_boost_not_clamped(self, tmp_path, monkeypatch):
        # a cell with its OWN n>=13 and a >1.0 mult keeps its boost — the clamp is
        # fallback-only (evidence-less cells), never applied to earned cells.
        rows = [_row(i, "BTC", "SELL", 0.9, 15.0) for i in range(13)]
        path = tmp_path / "trade_ledger.csv"
        _write_ledger(path, rows)
        monkeypatch.setattr(live_edge, "_LEDGER", str(path))
        monkeypatch.setenv("SIDE_LEVEL_EDGE", "true")
        monkeypatch.setenv("SIDE_FALLBACK_NO_BOOST", "true")
        live_edge._cache["ledger_mtime"] = -1.0
        assert live_edge.get_side_mult("BTC", "SELL") == live_edge._pnl_to_mult(15.0)  # 1.5, own cell
