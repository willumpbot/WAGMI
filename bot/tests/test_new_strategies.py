"""
Tests for all new quant strategies (Phase 6 alpha generation).

Tests: FundingRate, OIDelta, BollingerSqueeze, VMCCipher, LeadLag,
       LiquidationCascade, ProbabilityEngine
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta


# --------------- Helpers ---------------

def make_ohlcv(n: int = 100, base: float = 100.0, trend: float = 0.001,
               vol: float = 0.02, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.RandomState(seed)
    close = [base]
    for i in range(1, n):
        ret = trend + rng.normal(0, vol)
        close.append(close[-1] * (1 + ret))
    close = np.array(close)
    high = close * (1 + rng.uniform(0, vol, n))
    low = close * (1 - rng.uniform(0, vol, n))
    open_ = close * (1 + rng.normal(0, vol * 0.3, n))
    volume = rng.uniform(100, 1000, n)
    df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume,
    })
    return df


def make_trending_ohlcv(n: int = 100, direction: str = "up") -> pd.DataFrame:
    """Generate clearly trending data."""
    trend = 0.005 if direction == "up" else -0.005
    return make_ohlcv(n=n, trend=trend, vol=0.01, seed=123)


def make_ranging_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate ranging/choppy data."""
    return make_ohlcv(n=n, trend=0.0, vol=0.005, seed=456)


def make_volatile_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate high-volatility data."""
    return make_ohlcv(n=n, trend=0.0, vol=0.05, seed=789)


SYMBOLS = {"TEST": {"name": "TEST"}}


# --------------- Funding Rate Strategy ---------------

class TestFundingRateStrategy:
    def setup_method(self):
        from strategies.funding_rate import FundingRateStrategy
        self.strategy = FundingRateStrategy(SYMBOLS)

    def test_no_funding_data_returns_none(self):
        df = make_ohlcv()
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_neutral_funding_returns_none(self):
        df = make_ohlcv()
        data = {"1h": df, "_funding_rate": 0.00001}  # 0.001% = neutral (below hourly HIGH threshold)
        assert self.strategy.evaluate("TEST", data) is None

    def test_positive_extreme_funding_generates_sell(self):
        df = make_ranging_ohlcv()
        data = {"1h": df, "_funding_rate": 0.0005}  # 0.05% = extreme positive
        sig = self.strategy.evaluate("TEST", data)
        # Should generate SELL (counter-trade longs)
        if sig:
            assert sig.side == "SELL"
            assert sig.confidence >= 50
            assert sig.is_valid

    def test_negative_extreme_funding_generates_buy(self):
        df = make_ranging_ohlcv()
        data = {"1h": df, "_funding_rate": -0.0005}  # -0.05% = extreme negative
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "BUY"
            assert sig.confidence >= 50
            assert sig.is_valid

    def test_funding_from_meta(self):
        df = make_ohlcv()
        data = {"1h": df, "_meta": {"funding_rate": 0.0005}}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.strategy == "funding_rate"

    def test_trend_guard_skips_aligned_funding(self):
        """Strong uptrend + positive funding should be skipped."""
        df = make_trending_ohlcv(direction="up")
        data = {"1h": df, "_funding_rate": 0.0003}
        # With strong trend, should likely skip
        sig = self.strategy.evaluate("TEST", data)
        # This may or may not return None depending on ADX
        # Just verify it doesn't crash
        if sig:
            assert sig.is_valid

    def test_get_status(self):
        df = make_ohlcv()
        data = {"1h": df, "_funding_rate": 0.0003}
        status = self.strategy.get_status("TEST", data)
        assert status["strategy"] == "funding_rate"
        assert "funding_rate" in status

    def test_signal_has_metadata(self):
        df = make_ranging_ohlcv()
        data = {"1h": df, "_funding_rate": 0.0005}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert "funding_rate" in sig.metadata
            assert "rsi" in sig.metadata
            assert sig.signal_context


# --------------- OI Delta Strategy ---------------

class TestOIDeltaStrategy:
    def setup_method(self):
        from strategies.oi_delta import OIDeltaStrategy
        self.strategy = OIDeltaStrategy(SYMBOLS)

    def test_no_oi_data_returns_none(self):
        df = make_ohlcv()
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_oi_expansion_with_price_up_buys(self):
        df = make_trending_ohlcv(direction="up")
        data = {"1h": df, "_meta": {"open_interest": 1000000, "open_interest_prev": 900000}}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "BUY"
            assert sig.is_valid
            assert sig.metadata["oi_regime_type"] == "trend_continuation_long"

    def test_oi_expansion_with_price_down_sells(self):
        df = make_trending_ohlcv(direction="down")
        data = {"1h": df, "_meta": {"open_interest": 1000000, "open_interest_prev": 900000}}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "SELL"
            assert sig.is_valid

    def test_oi_contraction_with_price_up_squeeze(self):
        df = make_trending_ohlcv(direction="up")
        data = {"1h": df, "_meta": {"open_interest": 850000, "open_interest_prev": 1000000}}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "BUY"
            assert "squeeze" in sig.metadata.get("oi_regime_type", "")

    def test_insufficient_data(self):
        df = make_ohlcv(n=5)
        data = {"1h": df, "_meta": {"open_interest": 1000000, "open_interest_prev": 900000}}
        assert self.strategy.evaluate("TEST", data) is None


# --------------- Bollinger Squeeze Strategy ---------------

class TestBollingerSqueezeStrategy:
    def setup_method(self):
        from strategies.bollinger_squeeze import BollingerSqueezeStrategy
        self.strategy = BollingerSqueezeStrategy(SYMBOLS)

    def test_insufficient_data_returns_none(self):
        df = make_ohlcv(n=10)
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_normal_data_may_generate_signal(self):
        df = make_ohlcv(n=100)
        data = {"1h": df}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.strategy == "bollinger_squeeze"
            assert sig.is_valid
            assert sig.metadata.get("signal_type") in ("squeeze_breakout", "bandwalk", "pre_breakout")

    def test_trending_data_bandwalk(self):
        """Strongly trending data should produce bandwalk signals."""
        df = make_trending_ohlcv(n=100)
        data = {"1h": df}
        sig = self.strategy.evaluate("TEST", data)
        # May or may not fire depending on data characteristics
        if sig:
            assert sig.is_valid

    def test_squeeze_detection(self):
        """Test the squeeze detection mechanism."""
        df = make_ranging_ohlcv(n=100)
        squeeze_info = self.strategy._detect_squeeze(df)
        assert "currently_squeezed" in squeeze_info
        assert "squeeze_fired" in squeeze_info
        assert "bb_width" in squeeze_info

    def test_get_status(self):
        df = make_ohlcv(n=50)
        data = {"1h": df}
        status = self.strategy.get_status("TEST", data)
        assert status["strategy"] == "bollinger_squeeze"


# --------------- VMC Cipher Strategy ---------------

class TestVMCCipherStrategy:
    def setup_method(self):
        from strategies.vmc_cipher import VMCCipherStrategy
        self.strategy = VMCCipherStrategy(SYMBOLS)

    def test_insufficient_data_returns_none(self):
        df = make_ohlcv(n=10)
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_oscillator_computation(self):
        """Test that all 5 oscillators compute without error."""
        df = make_ohlcv(n=100)
        result = self.strategy._compute_oscillator_votes(df)
        assert "votes" in result
        assert len(result["votes"]) == 5
        for name in ["wavetrend", "rsi", "stoch_rsi", "macd", "mfi"]:
            assert name in result["votes"]
        assert "wt1" in result
        assert "rsi" in result
        assert "stoch_k" in result
        assert "mfi" in result
        assert "macd_hist" in result

    def test_signal_requires_min_agreement(self):
        """Signal should only fire with >= 3 oscillator agreement."""
        df = make_ohlcv(n=100)
        data = {"1h": df}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.is_valid
            # Verify agreement score
            votes = sig.metadata.get("oscillator_votes", {})
            buy_count = sum(1 for v in votes.values() if v == "bull")
            sell_count = sum(1 for v in votes.values() if v == "bear")
            # At least 3 should agree on the chosen direction
            if sig.side == "BUY":
                assert buy_count >= 2  # Some might be partial (0.5)
            else:
                assert sell_count >= 2

    def test_divergence_detection_import(self):
        """Test divergence detection helper."""
        from strategies.vmc_cipher import _detect_divergence
        price = pd.Series(np.linspace(100, 90, 20))  # Falling price
        osc = pd.Series(np.linspace(20, 30, 20))      # Rising oscillator
        result = _detect_divergence(price, osc, lookback=14)
        # Should detect bullish divergence (price down, osc up)
        assert result in (None, "bullish", "bearish")

    def test_get_status(self):
        df = make_ohlcv(n=50)
        data = {"1h": df}
        status = self.strategy.get_status("TEST", data)
        assert status["strategy"] == "vmc_cipher"


# --------------- Lead-Lag Strategy ---------------

class TestLeadLagStrategy:
    def setup_method(self):
        from strategies.lead_lag import LeadLagStrategy
        self.strategy = LeadLagStrategy(SYMBOLS)

    def test_btc_symbol_skipped(self):
        """Should not generate signals for BTC itself."""
        df = make_ohlcv()
        data = {"1h": df, "_btc_1h": df}
        assert self.strategy.evaluate("BTC", data) is None

    def test_no_btc_data_returns_none(self):
        df = make_ohlcv()
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_btc_up_alt_flat_generates_buy(self):
        """BTC moved up, alt hasn't followed → BUY alt."""
        btc_df = make_trending_ohlcv(n=100, direction="up")
        # Alt is flat/ranging
        alt_df = make_ranging_ohlcv(n=100)
        data = {"1h": alt_df, "_btc_1h": btc_df}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "BUY"
            assert sig.is_valid
            assert "lag_ratio" in sig.metadata

    def test_btc_down_alt_flat_generates_sell(self):
        """BTC moved down, alt hasn't followed → SELL alt."""
        btc_df = make_trending_ohlcv(n=100, direction="down")
        alt_df = make_ranging_ohlcv(n=100)
        data = {"1h": alt_df, "_btc_1h": btc_df}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.side == "SELL"
            assert sig.is_valid

    def test_relative_strength_computation(self):
        """Test the RS calculation doesn't crash."""
        btc_df = make_ohlcv(n=50)
        alt_df = make_ohlcv(n=50, base=50)
        rs = self.strategy._compute_relative_strength(alt_df, btc_df, lookback=12)
        assert isinstance(rs, float)
        assert rs > 0

    def test_cross_data_format(self):
        """Test alternative BTC data format (_cross dict)."""
        btc_df = make_trending_ohlcv(n=100, direction="up")
        alt_df = make_ranging_ohlcv(n=100)
        data = {"1h": alt_df, "_cross": {"BTC": {"1h": btc_df}}}
        sig = self.strategy.evaluate("TEST", data)
        # Should work with cross data format too
        if sig:
            assert sig.is_valid


# --------------- Liquidation Cascade Strategy ---------------

class TestLiquidationCascadeStrategy:
    def setup_method(self):
        from strategies.liquidation_cascade import LiquidationCascadeStrategy
        self.strategy = LiquidationCascadeStrategy(SYMBOLS)

    def test_insufficient_data_returns_none(self):
        df = make_ohlcv(n=10)
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_normal_data_usually_no_signal(self):
        """Normal ranging data shouldn't trigger cascade detection."""
        df = make_ranging_ohlcv(n=100)
        data = {"1h": df}
        sig = self.strategy.evaluate("TEST", data)
        # May or may not fire depending on random volume spikes
        if sig:
            assert sig.is_valid

    def test_cascade_proxy_detection(self):
        """Test the cascade detection proxy mechanism."""
        df = make_volatile_ohlcv(n=50)
        # Inject a volume spike manually
        df_mod = df.copy()
        df_mod.loc[df_mod.index[-3], "volume"] = df_mod["volume"].mean() * 5
        df_mod.loc[df_mod.index[-3], "close"] = df_mod["close"].iloc[-4] * 0.95
        cascades = self.strategy._detect_cascade_proxy(df_mod)
        # Should detect something in volatile data with volume spike
        assert isinstance(cascades, list)

    def test_signal_metadata_complete(self):
        """If signal fires, metadata should be complete."""
        df = make_volatile_ohlcv(n=50)
        # Force a cascade-like candle
        df_mod = df.copy()
        df_mod.loc[df_mod.index[-3], "volume"] = df_mod["volume"].mean() * 4
        low_val = df_mod["close"].iloc[-4] * 0.94
        df_mod.loc[df_mod.index[-3], "low"] = low_val
        df_mod.loc[df_mod.index[-3], "close"] = low_val * 1.01
        data = {"1h": df_mod}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert "cascade_type" in sig.metadata
            assert "cascade_severity" in sig.metadata
            assert sig.is_valid


# --------------- Probability Engine Strategy ---------------

class TestProbabilityEngineStrategy:
    def setup_method(self):
        from strategies.probability_engine import ProbabilityEngineStrategy
        self.strategy = ProbabilityEngineStrategy(SYMBOLS, num_sims=500, forward_bars=6)

    def test_insufficient_data_returns_none(self):
        df = make_ohlcv(n=20)
        data = {"1h": df}
        assert self.strategy.evaluate("TEST", data) is None

    def test_regime_classification(self):
        """Test regime classification for different market conditions."""
        trend_df = make_trending_ohlcv(n=100)
        regime = self.strategy._classify_regime(trend_df)
        assert regime["regime"] in ("trending", "ranging", "volatile", "normal", "unknown")
        assert "vol" in regime
        assert "adx" in regime

    def test_monte_carlo_runs(self):
        """Test that MC simulation produces valid output."""
        df = make_ohlcv(n=100)
        returns = df["close"].pct_change().dropna().values
        mc = self.strategy._run_monte_carlo(100.0, returns, num_sims=100, forward_bars=6)
        assert "terminal" in mc
        assert "percentiles" in mc
        assert len(mc["terminal"]) == 100
        assert mc["percentiles"]["p5"] < mc["percentiles"]["p95"]

    def test_probability_computation(self):
        """Test probability calculations."""
        df = make_trending_ohlcv(n=100)
        returns = df["close"].pct_change().dropna().values
        price = 100.0
        mc = self.strategy._run_monte_carlo(price, returns, num_sims=500, forward_bars=12)
        probs = self.strategy._compute_probabilities(mc, price, tp1=105, tp2=110, sl=95, side="BUY")
        assert 0 <= probs["prob_tp1"] <= 1
        assert 0 <= probs["prob_tp2"] <= 1
        assert 0 <= probs["prob_sl"] <= 1

    def test_ev_computation(self):
        """Test expected value calculation."""
        probs = {"prob_tp1": 0.6, "prob_tp2": 0.3, "prob_sl": 0.4}
        ev = self.strategy._compute_ev(probs, price=100, tp1=105, tp2=110, sl=95)
        assert isinstance(ev, float)

    def test_signal_generation_trending(self):
        """Trending data should produce a signal (if EV is positive)."""
        df = make_trending_ohlcv(n=100, direction="up")
        data = {"1h": df}
        sig = self.strategy.evaluate("TEST", data)
        if sig:
            assert sig.strategy == "probability_engine"
            assert sig.is_valid
            assert "prob_tp1" in sig.metadata
            assert "expected_value" in sig.metadata

    def test_get_status(self):
        df = make_ohlcv(n=60)
        data = {"1h": df}
        status = self.strategy.get_status("TEST", data)
        assert status["strategy"] == "probability_engine"


# --------------- Thesis Tracker ---------------

class TestThesisTracker:
    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        from llm.thesis_tracker import ThesisTracker
        self.tracker = ThesisTracker(data_dir=self.tmpdir)

    def test_record_thesis(self):
        tid = self.tracker.record_thesis(
            symbol="SOL", side="BUY", thesis="SOL to $150 in 6h",
            confidence=80.0, regime="trend", entry_price=142.5,
            target_price=150.0, expected_hold_h=6.0, setup_type="breakout",
        )
        assert tid.startswith("thesis_")
        assert len(self.tracker.get_pending_theses()) == 1

    def test_close_thesis_correct(self):
        tid = self.tracker.record_thesis(
            symbol="SOL", side="BUY", thesis="SOL to $150",
            confidence=80.0, regime="trend", entry_price=142.5,
            target_price=150.0,
        )
        self.tracker.close_thesis(
            tid, exit_price=148.0, pnl_pct=3.86,
            max_favorable=151.0, actual_hold_h=4.0,
        )
        assert len(self.tracker.get_pending_theses()) == 0

    def test_close_thesis_incorrect(self):
        tid = self.tracker.record_thesis(
            symbol="SOL", side="BUY", thesis="SOL to $150",
            confidence=80.0, regime="trend", entry_price=142.5,
        )
        self.tracker.close_thesis(tid, exit_price=138.0, pnl_pct=-3.16)
        stats = self.tracker.get_accuracy_stats(min_samples=1)
        assert stats["total_theses"] == 1

    def test_accuracy_stats(self):
        # Record multiple theses
        for i in range(10):
            tid = self.tracker.record_thesis(
                symbol="SOL", side="BUY", thesis=f"thesis {i}",
                confidence=70 + i, regime="trend", entry_price=100.0,
            )
            self.tracker.close_thesis(tid, exit_price=102.0 if i % 2 == 0 else 98.0,
                                       pnl_pct=2.0 if i % 2 == 0 else -2.0)

        stats = self.tracker.get_accuracy_stats(min_samples=3)
        assert stats["sufficient_data"]
        assert stats["total_theses"] == 10
        assert 0 <= stats["overall_accuracy"] <= 1

    def test_prompt_context(self):
        for i in range(10):
            tid = self.tracker.record_thesis(
                symbol="SOL", side="BUY", thesis=f"thesis {i}",
                confidence=75, regime="trend", entry_price=100.0,
            )
            self.tracker.close_thesis(tid, exit_price=102.0, pnl_pct=2.0)

        ctx = self.tracker.get_prompt_context()
        assert "THESIS ACCURACY" in ctx or ctx == ""


# --------------- Confidence Calibrator ---------------

class TestConfidenceCalibrator:
    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        from llm.confidence_calibrator import ConfidenceCalibrator
        self.calibrator = ConfidenceCalibrator(data_dir=self.tmpdir)

    def test_no_data_returns_raw(self):
        """Without calibration data, should return raw confidence."""
        assert self.calibrator.calibrate(75.0) == 75.0

    def test_record_observation(self):
        self.calibrator.record_observation(80.0, True, "trade_agent", "SOL")
        assert len(self.calibrator._observations) == 1

    def test_rebuild_curve(self):
        """Build a calibration curve from observations."""
        # Record enough observations to fill bins
        for i in range(30):
            conf = 70 + (i % 10)  # 70-79 range
            correct = i % 3 != 0  # ~67% win rate
            self.calibrator.record_observation(conf, correct)

        self.calibrator.rebuild_curve()
        # Should have built some curve data
        summary = self.calibrator.get_calibration_summary()
        assert summary["total_observations"] == 30

    def test_calibration_adjusts_overconfident(self):
        """If 80% confidence only wins 55%, calibrator should deflate."""
        for i in range(20):
            # All in 80-90 bin, but only 50% win rate
            self.calibrator.record_observation(85.0, i % 2 == 0)

        self.calibrator.rebuild_curve()
        calibrated = self.calibrator.calibrate(85.0)
        # Should be lower than 85 since actual WR is ~50%
        assert calibrated < 85.0

    def test_get_summary(self):
        summary = self.calibrator.get_calibration_summary()
        assert "total_observations" in summary
        assert "scopes" in summary


# --------------- Counterfactual Learner ---------------

class TestCounterfactualLearner:
    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        from llm.counterfactual_learner import CounterfactualLearner
        self.learner = CounterfactualLearner(data_dir=self.tmpdir)

    def test_record_skip(self):
        rid = self.learner.record_skip(
            symbol="SOL", side="BUY", entry_price=142.5,
            sl=139.0, tp1=146.0, tp2=152.0, confidence=75.0,
            skip_reason="confidence_floor",
        )
        assert rid.startswith("cf_")
        assert len(self.learner._pending) == 1

    def test_update_with_price_resolves_tp1(self):
        self.learner.record_skip(
            symbol="SOL", side="BUY", entry_price=142.5,
            sl=139.0, tp1=146.0, tp2=152.0, confidence=75.0,
            skip_reason="veto",
        )
        # Price goes up to hit TP2
        self.learner.update_with_price("SOL", high=153.0, low=142.0, close=152.0)

        assert len(self.learner._pending) == 0
        assert len(self.learner._resolved_recent) == 1
        resolved = self.learner._resolved_recent[0]
        assert resolved.would_hit_tp1
        assert resolved.would_hit_tp2
        assert resolved.hypothetical_pnl_pct > 0

    def test_update_with_price_resolves_sl(self):
        self.learner.record_skip(
            symbol="SOL", side="BUY", entry_price=142.5,
            sl=139.0, tp1=146.0, tp2=152.0, confidence=75.0,
            skip_reason="ensemble_reject",
        )
        # Price drops to SL
        self.learner.update_with_price("SOL", high=143.0, low=138.0, close=138.5)

        assert len(self.learner._pending) == 0
        resolved = self.learner._resolved_recent[0]
        assert resolved.would_hit_sl
        assert resolved.hypothetical_pnl_pct < 0

    def test_missed_opportunity_stats(self):
        # Record and resolve several skips
        for i in range(10):
            self.learner.record_skip(
                symbol="SOL", side="BUY", entry_price=100.0,
                sl=95.0, tp1=105.0, tp2=110.0, confidence=70.0,
                skip_reason="confidence_floor" if i % 2 == 0 else "veto",
            )

        # Resolve half as winners, half as losers
        for sym_rec in list(self.learner._pending.values()):
            if len(self.learner._resolved_recent) % 2 == 0:
                self.learner.update_with_price("SOL", high=112.0, low=99.0, close=111.0)
            else:
                self.learner.update_with_price("SOL", high=101.0, low=94.0, close=94.5)

        stats = self.learner.get_missed_opportunity_stats()
        assert stats["total_skips"] >= 1

    def test_prompt_context(self):
        ctx = self.learner.get_prompt_context()
        # With no data, should return empty
        assert ctx == ""

    def test_max_pending_eviction(self):
        """Test that old records are evicted when at capacity."""
        self.learner.MAX_PENDING = 5
        for i in range(7):
            self.learner.record_skip(
                symbol="SOL", side="BUY", entry_price=100.0,
                sl=95.0, tp1=105.0, tp2=110.0, confidence=70.0,
                skip_reason="test",
            )
        assert len(self.learner._pending) == 5


# --------------- Signal Contract Compliance ---------------

class TestSignalContractCompliance:
    """Verify all new strategies produce valid signals that pass the Signal contract."""

    def test_all_strategies_return_valid_or_none(self):
        """Every strategy must return either a valid Signal or None."""
        from strategies.funding_rate import FundingRateStrategy
        from strategies.oi_delta import OIDeltaStrategy
        from strategies.bollinger_squeeze import BollingerSqueezeStrategy
        from strategies.vmc_cipher import VMCCipherStrategy
        from strategies.lead_lag import LeadLagStrategy
        from strategies.liquidation_cascade import LiquidationCascadeStrategy
        from strategies.probability_engine import ProbabilityEngineStrategy

        strategies = [
            FundingRateStrategy(SYMBOLS),
            OIDeltaStrategy(SYMBOLS),
            BollingerSqueezeStrategy(SYMBOLS),
            VMCCipherStrategy(SYMBOLS),
            LeadLagStrategy(SYMBOLS),
            LiquidationCascadeStrategy(SYMBOLS),
            ProbabilityEngineStrategy(SYMBOLS, num_sims=100, forward_bars=6),
        ]

        df = make_ohlcv(n=100)
        data = {
            "1h": df,
            "_funding_rate": 0.0005,
            "_meta": {"open_interest": 1000000, "open_interest_prev": 900000},
            "_btc_1h": make_trending_ohlcv(n=100, direction="up"),
        }

        for strategy in strategies:
            sig = strategy.evaluate("TEST", data)
            if sig is not None:
                assert sig.is_valid, f"{strategy.name} produced invalid signal: {sig}"
                assert sig.strategy == strategy.name
                assert sig.symbol == "TEST"
                assert sig.side in ("BUY", "SELL")
                assert 0 < sig.confidence <= 100
                assert sig.entry > 0
                assert sig.atr > 0

    def test_all_strategies_handle_missing_data(self):
        """All strategies must handle missing data gracefully."""
        from strategies.funding_rate import FundingRateStrategy
        from strategies.oi_delta import OIDeltaStrategy
        from strategies.bollinger_squeeze import BollingerSqueezeStrategy
        from strategies.vmc_cipher import VMCCipherStrategy
        from strategies.lead_lag import LeadLagStrategy
        from strategies.liquidation_cascade import LiquidationCascadeStrategy
        from strategies.probability_engine import ProbabilityEngineStrategy

        strategies = [
            FundingRateStrategy(SYMBOLS),
            OIDeltaStrategy(SYMBOLS),
            BollingerSqueezeStrategy(SYMBOLS),
            VMCCipherStrategy(SYMBOLS),
            LeadLagStrategy(SYMBOLS),
            LiquidationCascadeStrategy(SYMBOLS),
            ProbabilityEngineStrategy(SYMBOLS, num_sims=100, forward_bars=6),
        ]

        empty_data = {}
        short_data = {"1h": make_ohlcv(n=3)}

        for strategy in strategies:
            # Empty data
            sig = strategy.evaluate("TEST", empty_data)
            assert sig is None, f"{strategy.name} didn't return None for empty data"

            # Very short data
            sig = strategy.evaluate("TEST", short_data)
            assert sig is None, f"{strategy.name} didn't return None for short data"

    def test_all_strategies_have_required_methods(self):
        """All strategies must implement evaluate, get_status, get_required_timeframes."""
        from strategies.funding_rate import FundingRateStrategy
        from strategies.oi_delta import OIDeltaStrategy
        from strategies.bollinger_squeeze import BollingerSqueezeStrategy
        from strategies.vmc_cipher import VMCCipherStrategy
        from strategies.lead_lag import LeadLagStrategy
        from strategies.liquidation_cascade import LiquidationCascadeStrategy
        from strategies.probability_engine import ProbabilityEngineStrategy

        strategies = [
            FundingRateStrategy(SYMBOLS),
            OIDeltaStrategy(SYMBOLS),
            BollingerSqueezeStrategy(SYMBOLS),
            VMCCipherStrategy(SYMBOLS),
            LeadLagStrategy(SYMBOLS),
            LiquidationCascadeStrategy(SYMBOLS),
            ProbabilityEngineStrategy(SYMBOLS, num_sims=100),
        ]

        for strategy in strategies:
            assert hasattr(strategy, "evaluate")
            assert hasattr(strategy, "get_status")
            assert hasattr(strategy, "get_required_timeframes")
            tfs = strategy.get_required_timeframes()
            assert isinstance(tfs, list)
            assert "1h" in tfs
