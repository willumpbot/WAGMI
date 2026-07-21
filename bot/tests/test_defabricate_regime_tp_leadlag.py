"""
Tests for RIP-OUT PHASE 1: DEFABRICATE_REGIME_TP (#5) + DEFABRICATE_LEAD_LAG (#7).

#5 -- trading_config.REGIME_SL_TP_SCALARS tp1_mult/tp2_mult columns are
static and admittedly stale (the table's own comments concede there is no
live TP path yet). get_regime_sl_tp() applies them verbatim to every signal
placed by strategies/confidence_scorer.py and strategies/regime_trend.py.
DEFABRICATE_REGIME_TP (default off) replaces that scaling with a neutral
1.0 clamp (the caller's base TP, unscaled) when on. SL is untouched either
way -- it already has its own live, symmetric, ledger-blended path.

#7 -- trading_config.LEAD_LAG_SYMBOL_CONFIG beta/lag_minutes (and a
duplicate static fallback dict in execution/cross_asset_alert.py) are a
hand-set, never-corroborated per-symbol table. DEFABRICATE_LEAD_LAG
(default off) replaces beta/lag_minutes with values computed live from
LeadLagBoostEngine's own rolling BTC/follower return windows (the same
data already used for real-time correlation), falling back to a neutral
default -- never the fabricated per-symbol value -- when there isn't yet
enough evidence (n>=13). The boost_cap side is unaffected (already live via
get_lead_lag_boost_cap / DATA_DRIVEN_LEAD_LAG_CAP).

Both flags default to false -> byte-identical current behavior. All ledger/
dynamic-threshold access is mocked or disabled -- these tests never read or
write real ledger/trade_dna data.
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import trading_config
import llm.dynamic_thresholds as _dynamic_thresholds_mod
import feedback.live_edge as _live_edge_mod
from execution.cross_asset_alert import LeadLagBoostEngine


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _blocked_dynamic_thresholds():
    raise RuntimeError("blocked-in-test: real trade_dna.json must not be touched")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Never leak DEFABRICATE_* flags between tests; never touch real
    trade_ledger.csv / trade_dna.json."""
    monkeypatch.delenv("DEFABRICATE_REGIME_TP", raising=False)
    monkeypatch.delenv("DEFABRICATE_LEAD_LAG", raising=False)
    # Block get_regime_sl_tp's live SL paths from touching real data files;
    # #5 only cares about the TP columns, which never touch these paths, but
    # keeping them mocked keeps every test in this module fully hermetic.
    monkeypatch.setattr(trading_config, "_get_regime_sl_hit_rate_ledger", lambda regime: None)
    monkeypatch.setattr(_dynamic_thresholds_mod, "get_dynamic_thresholds", _blocked_dynamic_thresholds)
    # get_lead_lag_boost_cap() (called by LeadLagBoostEngine's already-live
    # cap path, unrelated to #7 but on the same call chain) reads the real
    # ledger via feedback.live_edge.get_report -- force the "insufficient
    # evidence" branch so the cap stays the deterministic static fallback
    # instead of depending on whatever is in the real trade_ledger.csv.
    monkeypatch.setattr(_live_edge_mod, "get_report", lambda: {})
    yield


def _set_flag(monkeypatch, name, value):
    monkeypatch.setenv(name, "true" if value else "false")


# ===========================================================================
# #5 — DEFABRICATE_REGIME_TP
# ===========================================================================

class TestDefabricateRegimeTP:

    def test_flag_off_static_tp_scalars_applied(self, monkeypatch):
        """Characterization: flag off (default) -> static REGIME_SL_TP_SCALARS
        tp1_mult/tp2_mult applied verbatim, exactly as before this change."""
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", False)
        sl, tp1, tp2 = trading_config.get_regime_sl_tp("trending_bull", 1.0, 2.0, 4.0)
        scalars = trading_config.REGIME_SL_TP_SCALARS["trending_bull"]
        assert tp1 == pytest.approx(2.0 * scalars["tp1_mult"])
        assert tp2 == pytest.approx(4.0 * scalars["tp2_mult"])
        # Also true when DEFABRICATE_REGIME_TP is simply unset (default).
        monkeypatch.delenv("DEFABRICATE_REGIME_TP", raising=False)
        sl2, tp1_2, tp2_2 = trading_config.get_regime_sl_tp("trending_bull", 1.0, 2.0, 4.0)
        assert (tp1_2, tp2_2) == (tp1, tp2)

    def test_flag_on_tp_neutral_mult(self, monkeypatch):
        """Flag on -> tp1_mult/tp2_mult clamp to 1.0 (base TP unscaled)."""
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", True)
        sl, tp1, tp2 = trading_config.get_regime_sl_tp("trending_bull", 1.0, 2.0, 4.0)
        assert tp1 == pytest.approx(2.0)
        assert tp2 == pytest.approx(4.0)

    def test_flag_on_sl_unchanged_vs_flag_off(self, monkeypatch):
        """SL must be byte-identical regardless of DEFABRICATE_REGIME_TP --
        the flag only touches the TP columns."""
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", False)
        sl_off, _, _ = trading_config.get_regime_sl_tp("range", 1.5, 2.0, 4.0)
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", True)
        sl_on, _, _ = trading_config.get_regime_sl_tp("range", 1.5, 2.0, 4.0)
        assert sl_on == sl_off

    @pytest.mark.parametrize("side,entry,atr", [("BUY", 100.0, 2.0), ("SELL", 100.0, 2.0)])
    def test_flag_on_tp_stays_valid_correct_side_and_rr(self, monkeypatch, side, entry, atr):
        """Mirrors the SL/TP placement formula used by
        strategies/confidence_scorer.py:755-766 and
        strategies/regime_trend.py:306-314 (K=sl_mult, tp=entry +/- mult*stop_width).
        With the flag on, tp1_mult/tp2_mult come back as the callers' own
        base values (2.0 / 4.0) unscaled -- TP must remain on the correct
        side of entry and R:R (tp1_mult itself, by construction) must stay >= 1."""
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", True)
        base_sl_mult, base_tp1_mult, base_tp2_mult = 1.5, 2.0, 4.0
        K, tp1_mult, tp2_mult = trading_config.get_regime_sl_tp(
            "high_volatility", base_sl_mult, base_tp1_mult, base_tp2_mult
        )
        sl = entry - K * atr if side == "BUY" else entry + K * atr
        stop_width = abs(entry - sl)
        tp1 = entry + tp1_mult * stop_width if side == "BUY" else entry - tp1_mult * stop_width
        tp2 = entry + tp2_mult * stop_width if side == "BUY" else entry - tp2_mult * stop_width

        # Correct side
        if side == "BUY":
            assert sl < entry < tp1 <= tp2 or sl < entry < tp1 < tp2
        else:
            assert tp2 <= tp1 < entry < sl or tp2 < tp1 < entry < sl

        rr = abs(entry - tp1) / stop_width
        assert rr >= 1.0
        assert tp1_mult == pytest.approx(base_tp1_mult)
        assert tp2_mult == pytest.approx(base_tp2_mult)

    def test_unknown_regime_passthrough_both_flag_states(self, monkeypatch):
        """Regime not in the table -> always pass through base values
        unchanged, regardless of the flag (pre-existing behavior, untouched)."""
        for flag in (False, True):
            _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", flag)
            sl, tp1, tp2 = trading_config.get_regime_sl_tp("unknown", 1.5, 2.0, 4.0)
            assert (sl, tp1, tp2) == (1.5, 2.0, 4.0)

    def test_shadow_log_format(self, monkeypatch, caplog):
        import logging
        scalars = trading_config.REGIME_SL_TP_SCALARS["consolidation"]

        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", False)
        with caplog.at_level(logging.INFO, logger="trading_config"):
            trading_config.get_regime_sl_tp("consolidation", 1.0, 2.0, 4.0)
        msgs = [r.message for r in caplog.records if "[DEFAB-REGIME-TP]" in r.message]
        assert any("regime=consolidation" in m for m in msgs)
        assert any(f"fabricated_tp1_mult={scalars['tp1_mult']}" in m for m in msgs)
        assert any(f"fabricated_tp2_mult={scalars['tp2_mult']}" in m for m in msgs)
        assert any("acting=fabricated_static" in m for m in msgs)

        caplog.clear()
        _set_flag(monkeypatch, "DEFABRICATE_REGIME_TP", True)
        with caplog.at_level(logging.INFO, logger="trading_config"):
            trading_config.get_regime_sl_tp("consolidation", 1.0, 2.0, 4.0)
        msgs = [r.message for r in caplog.records if "[DEFAB-REGIME-TP]" in r.message]
        assert any("acting=neutral_1.0" in m for m in msgs)


# ===========================================================================
# #7 — DEFABRICATE_LEAD_LAG
# ===========================================================================

def _make_engine(**kwargs):
    defaults = dict(
        btc_move_threshold=0.3,
        max_boost=12.0,
        min_correlation=0.10,   # low floor so correlation gating doesn't block test signals
        correlation_decay=0.98,
        enabled=True,
    )
    defaults.update(kwargs)
    return LeadLagBoostEngine(**defaults)


def _feed_correlated_series(engine, symbol="SOL", n=40, start_time=1_000_000.0,
                             interval_s=60.0, lag_samples=0, seed=42):
    """Feed BTC + a follower whose returns are the SAME non-periodic random
    return series as BTC's, delayed by `lag_samples` update ticks, to build
    up the rolling _btc_returns / _follower_returns windows LeadLagBoostEngine
    already maintains (the same data _live_beta_lag reads). Non-periodic
    (uniform random, seeded) so a lag shift is actually distinguishable from
    lag=0 -- a periodic signal would tie at every even/odd offset.

    btc_move_threshold is temporarily disabled while feeding: a multi-tick
    random walk can otherwise accidentally cross the real 0.3% momentum
    threshold mid-feed, creating an EARLY LeadSignal that then blocks (via
    the 5-min per-symbol cooldown) the test's own explicit, controlled
    triggering call later. Restored before returning so callers still get
    the engine's real threshold for their own trigger call.
    """
    orig_threshold = engine.btc_move_threshold
    engine.btc_move_threshold = 1e9  # unreachable -- no momentum during feed
    try:
        rnd = random.Random(seed)
        btc_price = 50000.0
        foll_price = 100.0
        btc_rets = []
        for i in range(n):
            t = start_time + i * interval_s
            ret = rnd.uniform(-0.01, 0.01)
            btc_rets.append(ret)
            btc_price *= (1 + ret)
            engine.update_btc_price(btc_price, volume=100.0, current_time=t)

            # Follower reacts to BTC's return from `lag_samples` steps ago.
            src_idx = i - lag_samples
            foll_ret = btc_rets[src_idx] if src_idx >= 0 else 0.0
            foll_price *= (1 + foll_ret)
            engine.update_follower_price(symbol, foll_price, current_time=t)
    finally:
        engine.btc_move_threshold = orig_threshold
    return engine


class TestDefabricateLeadLag:

    def test_flag_off_static_beta_lag_used(self, monkeypatch):
        """Characterization: flag off (default) -> static lag_minutes from
        LEAD_LAG_SYMBOL_CONFIG drives the created LeadSignal's timing window,
        exactly as before this change."""
        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", False)
        engine = _make_engine()
        assert engine._symbol_configs["SOL"]["beta"] == 1.16
        assert engine._symbol_configs["SOL"]["lag_minutes"] == (30, 60)

        signals = _feed_correlated_series(engine, "SOL", n=5, lag_samples=0)
        # Real-time correlation is a separate (pre-existing, already-live)
        # gate unrelated to #7's beta/lag scope -- pin it high so this test
        # only exercises the lag_minutes source under test.
        engine._realtime_correlation["SOL"] = 0.95
        # Force a decisive move regardless of the small window above.
        t = 1_000_000.0 + 5 * 60.0
        engine.update_btc_price(52000.0, volume=100.0, current_time=t)
        sol_signals = [s for s in engine._lead_signals if s.follower == "SOL"]
        assert sol_signals, "expected a SOL lead signal"
        sig = sol_signals[0]
        assert sig.active_after - sig.created_at == pytest.approx(30 * 60)
        assert sig.expires_at - sig.created_at == pytest.approx(60 * 60)

    def test_flag_on_sufficient_n_uses_live_beta_lag(self, monkeypatch):
        """Flag on + enough paired return observations (n>=13) -> live
        beta/lag from _live_beta_lag() drive the LeadSignal timing, NOT the
        fabricated static (30, 60)."""
        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", True)
        engine = _make_engine()
        _feed_correlated_series(engine, "SOL", n=30, lag_samples=2)

        # Sanity: enough evidence exists before the triggering move.
        assert engine._live_beta_lag("SOL")["n"] >= engine._MIN_LIVE_LEAD_LAG_N
        # Real-time correlation is a separate (pre-existing, already-live)
        # gate unrelated to #7's beta/lag scope -- pin it high so this test
        # only exercises the lag_minutes source under test.
        engine._realtime_correlation["SOL"] = 0.95

        # Trigger a decisive BTC move to create a lead signal.
        t = 1_000_000.0 + 30 * 60.0
        engine.update_btc_price(60000.0, volume=500.0, current_time=t)
        sol_signals = [s for s in engine._lead_signals if s.follower == "SOL"]
        assert sol_signals, "expected a SOL lead signal"
        sig = sol_signals[-1]

        # Recompute AFTER the trigger -- same engine state _check_btc_momentum
        # used internally to build the signal, so this is a direct check that
        # the signal's timing came from _live_beta_lag's output.
        live = engine._live_beta_lag("SOL")
        assert live is not None
        lag_min, lag_max = live["lag_minutes"]
        assert (sig.active_after - sig.created_at) / 60.0 == pytest.approx(lag_min, abs=0.01)
        assert (sig.expires_at - sig.created_at) / 60.0 == pytest.approx(lag_max, abs=0.01)
        # Must differ from the fabricated static SOL window (30, 60) -- this
        # is the whole point of the flag. live windows are bounded to
        # [0, _MAX_LAG_SAMPLES] samples (<=20 min low side / <=35 min high
        # side here), which can never coincide with the static (30, 60).
        assert (lag_min, lag_max) != (30.0, 60.0)
        # realtime_beta diagnostics populated only when flag is on.
        assert "SOL" in engine._realtime_beta
        assert 0.3 <= engine._realtime_beta["SOL"] <= 3.0

    def test_flag_on_insufficient_n_uses_neutral_default(self, monkeypatch):
        """Flag on but too few paired observations (n<13) -> neutral default
        lag_minutes, NEVER the fabricated per-symbol static value."""
        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", True)
        engine = _make_engine()
        _feed_correlated_series(engine, "SOL", n=5, lag_samples=0)

        assert engine._live_beta_lag("SOL") is None  # not enough evidence
        # Real-time correlation is a separate (pre-existing, already-live)
        # gate unrelated to #7's beta/lag scope -- pin it high so this test
        # only exercises the lag_minutes source under test.
        engine._realtime_correlation["SOL"] = 0.95

        t = 1_000_000.0 + 5 * 60.0
        engine.update_btc_price(52000.0, volume=100.0, current_time=t)
        sol_signals = [s for s in engine._lead_signals if s.follower == "SOL"]
        assert sol_signals, "expected a SOL lead signal"
        sig = sol_signals[0]
        neutral_lo, neutral_hi = engine._NEUTRAL_LAG_MINUTES
        assert (sig.active_after - sig.created_at) / 60.0 == pytest.approx(neutral_lo)
        assert (sig.expires_at - sig.created_at) / 60.0 == pytest.approx(neutral_hi)
        # Must NOT be the fabricated SOL static window.
        assert (neutral_lo, neutral_hi) != (30.0, 60.0)

    def test_duplicate_static_dict_bypassed_when_flag_on(self, monkeypatch):
        """When trading_config.LEAD_LAG_SYMBOL_CONFIG is unavailable (forces
        the duplicate static fallback dict at cross_asset_alert.py:~440), the
        flag still governs: ON -> neutral beta/lag (never the fabricated
        duplicate values); OFF -> the old fabricated duplicate dict exactly
        as before. correlation/boost_cap (out of scope for #7) are the same
        in both cases."""
        monkeypatch.delattr(trading_config, "LEAD_LAG_SYMBOL_CONFIG", raising=False)

        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", True)
        engine_on = _make_engine()
        assert engine_on._symbol_configs["SOL"]["beta"] == engine_on._NEUTRAL_BETA
        assert engine_on._symbol_configs["SOL"]["lag_minutes"] == engine_on._NEUTRAL_LAG_MINUTES
        assert engine_on._symbol_configs["SOL"]["correlation"] == 0.87
        assert engine_on._symbol_configs["SOL"]["boost_cap"] == 12.0

        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", False)
        engine_off = _make_engine()
        assert engine_off._symbol_configs["SOL"]["beta"] == 1.16
        assert engine_off._symbol_configs["SOL"]["lag_minutes"] == (30, 60)
        # monkeypatch.delattr auto-restores LEAD_LAG_SYMBOL_CONFIG on teardown.

    def test_boost_stays_within_existing_cap(self, monkeypatch):
        """Regardless of the flag / live beta-lag path, the confidence boost
        applied must never exceed the existing (already-live)
        get_lead_lag_boost_cap ceiling -- #7 does not touch cap logic."""
        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", True)
        engine = _make_engine()
        monkeypatch.setattr(engine, "_effective_boost_cap", lambda symbol, side, cfg: 3.0)
        _feed_correlated_series(engine, "SOL", n=30, lag_samples=1)
        engine._realtime_correlation["SOL"] = 0.95

        t = 1_000_000.0 + 30 * 60.0
        # A large, decisive move that would otherwise produce a big raw_boost.
        engine.update_btc_price(80000.0, volume=1000.0, current_time=t)
        sol_signals = [s for s in engine._lead_signals if s.follower == "SOL"]
        assert sol_signals
        assert all(s.boost <= 3.0 + 1e-9 for s in sol_signals)

    def test_shadow_log_format(self, monkeypatch, caplog):
        import logging
        _set_flag(monkeypatch, "DEFABRICATE_LEAD_LAG", False)
        engine = _make_engine()
        _feed_correlated_series(engine, "SOL", n=5, lag_samples=0)
        t = 1_000_000.0 + 5 * 60.0
        with caplog.at_level(logging.INFO, logger="execution.cross_asset_alert"):
            engine.update_btc_price(52000.0, volume=100.0, current_time=t)
        msgs = [r.message for r in caplog.records if "[DEFAB-LEAD-LAG]" in r.message]
        assert any("symbol=SOL" in m and "fabricated_beta=1.16" in m and "fabricated_lag=(30, 60)" in m
                    for m in msgs)
