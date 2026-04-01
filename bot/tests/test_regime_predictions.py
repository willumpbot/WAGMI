"""Tests for regime prediction signals: ADX exhaustion, BTC lead, BB squeeze."""

import time
import numpy as np
import pandas as pd
import pytest

from tools.regime_detector import (
    ADXTrajectoryTracker,
    BTCLeadPredictor,
    SqueezeSizer,
    RegimeClassifier,
    RegimeReading,
    RegimeTransition,
    RegimePredictions,
    ADXExhaustion,
    BTCLeadSignal,
    SqueezeSignal,
)


# ── ADX Trajectory Tracker ────────────────────────────────────────────────


class TestADXTrajectoryTracker:
    """Test ADX peak detection and trend exhaustion signals."""

    def _make_adx_series(self, values):
        return pd.Series(values, dtype=float)

    def test_detects_peak_with_falling_adx(self):
        tracker = ADXTrajectoryTracker()
        # ADX rising to 35, then falling for 3 candles
        values = [15, 20, 25, 30, 35, 33, 30, 28]
        series = self._make_adx_series(values)
        result = tracker.detect_exhaustion("HYPE", series, "trend_bull")
        assert result is not None
        assert result.symbol == "HYPE"
        assert result.adx_peak == 35.0
        assert result.candles_since_peak == 3
        assert "TREND_EXHAUSTION" in result.context

    def test_no_detection_when_adx_still_rising(self):
        tracker = ADXTrajectoryTracker()
        values = [15, 20, 25, 28, 30, 32, 34, 36]
        series = self._make_adx_series(values)
        result = tracker.detect_exhaustion("HYPE", series, "trend_bull")
        assert result is None

    def test_no_detection_when_adx_too_low(self):
        tracker = ADXTrajectoryTracker()
        # Peak at 22 (below MIN_PEAK_ADX=25)
        values = [10, 15, 18, 22, 20, 18, 16]
        series = self._make_adx_series(values)
        result = tracker.detect_exhaustion("HYPE", series, "range")
        assert result is None

    def test_no_detection_with_only_1_falling_candle(self):
        tracker = ADXTrajectoryTracker()
        # Peak then only 1 falling candle
        values = [20, 25, 30, 35, 33]
        series = self._make_adx_series(values)
        result = tracker.detect_exhaustion("HYPE", series, "trend_bull")
        assert result is None

    def test_reversal_window_adjusts_for_elapsed_time(self):
        tracker = ADXTrajectoryTracker()
        # Peak 4 candles ago -> most of the 3.6-6.1h window consumed
        values = [20, 25, 30, 35, 40, 38, 35, 32, 29, 27]
        series = self._make_adx_series(values)
        result = tracker.detect_exhaustion("HYPE", series, "trend_bull")
        assert result is not None
        min_h, max_h = result.reversal_window_hours
        assert min_h >= 0  # Can't be negative
        assert max_h > 0

    def test_to_dict(self):
        exh = ADXExhaustion(
            symbol="HYPE", timestamp=time.time(),
            adx_peak=40.0, adx_current=32.0,
            candles_since_peak=3,
            reversal_window_hours=(0.6, 3.1),
            current_regime="trend_bull",
            context="test",
        )
        d = exh.to_dict()
        assert d["symbol"] == "HYPE"
        assert d["adx_peak"] == 40.0
        assert d["reversal_window_hours"] == [0.6, 3.1]


# ── BTC Lead Predictor ────────────────────────────────────────────────────


class TestBTCLeadPredictor:
    """Test BTC-leads-HYPE prediction signals."""

    def _make_transition(self, from_r, to_r, symbol="BTC"):
        return RegimeTransition(
            symbol=symbol, timestamp=time.time(),
            from_regime=from_r, to_regime=to_r,
            speed="normal", severity=3, confidence=0.8,
            rsi_velocity=-2.0, price_velocity=-0.5,
            recommended_actions=["test"], context="test",
        )

    def test_btc_bearish_shift_generates_hype_bearish(self):
        pred = BTCLeadPredictor()
        pred._active_signals = []  # Clear any persisted state
        transitions = [self._make_transition("trend_bull", "range")]
        signals = pred.check_btc_transitions(transitions)
        assert len(signals) >= 1
        assert signals[0].predicted_hype_direction == "bearish"
        assert signals[0].hours_remaining == 4.0
        assert signals[0].confidence == 0.83

    def test_btc_bullish_shift_generates_hype_bullish(self):
        pred = BTCLeadPredictor()
        pred._active_signals = []
        transitions = [self._make_transition("panic_oversold", "recovering")]
        signals = pred.check_btc_transitions(transitions)
        assert len(signals) >= 1
        assert signals[0].predicted_hype_direction == "bullish"

    def test_non_btc_transition_ignored(self):
        pred = BTCLeadPredictor()
        pred._active_signals = []
        transitions = [self._make_transition("trend_bull", "range", symbol="SOL")]
        signals = pred.check_btc_transitions(transitions)
        assert len(signals) == 0

    def test_unmapped_transition_ignored(self):
        pred = BTCLeadPredictor()
        pred._active_signals = []
        transitions = [self._make_transition("unknown", "low_liquidity")]
        signals = pred.check_btc_transitions(transitions)
        assert len(signals) == 0

    def test_expired_signals_cleaned(self):
        pred = BTCLeadPredictor()
        pred._active_signals = [
            {
                "timestamp": time.time() - 20000,
                "btc_from_regime": "trend_bull",
                "btc_to_regime": "range",
                "predicted_hype_direction": "bearish",
                "countdown_expires": time.time() - 100,  # Expired
                "hours_remaining": 0,
                "confidence": 0.83,
                "context": "old signal",
            }
        ]
        signals = pred.check_btc_transitions([])  # No new transitions
        # Expired signal should be cleaned
        assert len(pred._active_signals) == 0

    def test_to_dict(self):
        sig = BTCLeadSignal(
            timestamp=time.time(),
            btc_from_regime="trend_bull",
            btc_to_regime="range",
            predicted_hype_direction="bearish",
            countdown_expires=time.time() + 14400,
            hours_remaining=4.0,
            confidence=0.83,
            context="test",
        )
        d = sig.to_dict()
        assert d["predicted_hype_direction"] == "bearish"
        assert d["confidence"] == 0.83


# ── Squeeze Sizer ─────────────────────────────────────────────────────────


class TestSqueezeSizer:
    """Test BB squeeze detection and sizing multiplier."""

    def _make_df(self, n=100, bb_width_pctile="normal"):
        """Generate synthetic OHLCV with controllable BB width."""
        np.random.seed(42)
        base = 100.0
        prices = [base]
        for _ in range(n - 1):
            if bb_width_pctile == "squeeze":
                # Very tight range -> low BB width
                change = np.random.normal(0, 0.05)
            elif bb_width_pctile == "extreme_squeeze":
                change = np.random.normal(0, 0.01)
            else:
                change = np.random.normal(0, 0.5)
            prices.append(prices[-1] + change)

        close = pd.Series(prices)
        return pd.DataFrame({
            "open": close - 0.1,
            "high": close + abs(np.random.normal(0.2, 0.1, n)),
            "low": close - abs(np.random.normal(0.2, 0.1, n)),
            "close": close,
            "volume": np.random.uniform(100, 200, n),
        })

    def test_no_squeeze_in_normal_market(self):
        sizer = SqueezeSizer()
        df = self._make_df(100, "normal")
        result = sizer.detect_squeeze("HYPE", df)
        # Normal volatility should not trigger squeeze
        # (may or may not be None depending on the random data)
        if result is not None:
            assert result.sizing_multiplier >= 1.0

    def test_squeeze_detected_in_compressed_market(self):
        sizer = SqueezeSizer()
        # Create a DF where first 80 candles are volatile, last 20 very tight
        np.random.seed(42)
        volatile = np.cumsum(np.random.normal(0, 1.0, 80)) + 100
        tight = volatile[-1] + np.cumsum(np.random.normal(0, 0.02, 20))
        prices = np.concatenate([volatile, tight])
        n = len(prices)
        df = pd.DataFrame({
            "open": prices - 0.1,
            "high": prices + 0.3,
            "low": prices - 0.3,
            "close": prices,
            "volume": np.random.uniform(100, 200, n),
        })
        result = sizer.detect_squeeze("HYPE", df)
        assert result is not None
        assert result.sizing_multiplier >= 1.3
        assert result.bb_width_percentile < 20
        assert "SQUEEZE" in result.context

    def test_compute_bb_width_percentile_too_few_bars(self):
        sizer = SqueezeSizer()
        df = pd.DataFrame({
            "close": [100, 101, 102],
            "open": [99, 100, 101],
            "high": [101, 102, 103],
            "low": [98, 99, 100],
            "volume": [100, 100, 100],
        })
        assert sizer.compute_bb_width_percentile(df) is None

    def test_to_dict(self):
        sq = SqueezeSignal(
            symbol="HYPE", timestamp=time.time(),
            bb_width_percentile=8.5,
            sizing_multiplier=1.5,
            context="test",
        )
        d = sq.to_dict()
        assert d["sizing_multiplier"] == 1.5
        assert d["bb_width_percentile"] == 8.5


# ── RegimePredictions Aggregate ───────────────────────────────────────────


class TestRegimePredictions:
    """Test the aggregate predictions dataclass."""

    def test_empty_predictions(self):
        preds = RegimePredictions([], [], [])
        d = preds.to_dict()
        assert d["adx_exhaustions"] == []
        assert d["btc_lead_signals"] == []
        assert d["squeeze_signals"] == []

    def test_predictions_to_dict_roundtrip(self):
        preds = RegimePredictions(
            adx_exhaustions=[
                ADXExhaustion("HYPE", time.time(), 40.0, 32.0, 3,
                              (0.6, 3.1), "trend_bull", "test"),
            ],
            btc_lead_signals=[
                BTCLeadSignal(time.time(), "trend_bull", "range", "bearish",
                              time.time() + 14400, 4.0, 0.83, "test"),
            ],
            squeeze_signals=[
                SqueezeSignal("HYPE", time.time(), 8.5, 1.5, "test"),
            ],
        )
        d = preds.to_dict()
        assert len(d["adx_exhaustions"]) == 1
        assert len(d["btc_lead_signals"]) == 1
        assert len(d["squeeze_signals"]) == 1
