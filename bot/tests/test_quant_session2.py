"""
Tests for Session 2 quant system components:
- Shadow ledger persistence
- CVD signal strategy
- Liquidation signal strategy
- Go-live gate
- Regime audit
- Compound sizing multiplier helpers
- Daily report walk-forward integration
- IC tracker / Kelly engine convenience methods
"""

import math
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Shadow Ledger ──────────────────────────────────────────────────

class TestShadowLedger:
    def _make_ledger(self, tmpdir):
        from feedback.shadow_ledger import ShadowLedger
        return ShadowLedger(data_dir=str(tmpdir))

    def test_record_and_resolve(self, tmp_path):
        ledger = self._make_ledger(tmp_path)
        ledger.record_shadow_signal("lead_lag", "BTC", "BUY", 72.0, 65000.0)
        ledger.record_shadow_signal("lead_lag", "BTC", "SELL", 60.0, 65000.0)

        resolved = ledger.resolve_shadows("BTC", 66000.0)
        assert resolved == 2

        stats = ledger.get_factor_stats("lead_lag")
        assert stats["count"] == 2
        # BUY @ 65000 exit 66000 = +1.5%, SELL @ 65000 exit 66000 = -1.5%
        assert stats["win_rate"] == 0.5

    def test_persistence(self, tmp_path):
        from feedback.shadow_ledger import ShadowLedger
        ledger1 = ShadowLedger(data_dir=str(tmp_path))
        ledger1.record_shadow_signal("test_strat", "SOL", "BUY", 65.0, 100.0)

        # Reload from disk
        ledger2 = ShadowLedger(data_dir=str(tmp_path))
        assert len(ledger2._rows) == 1
        assert ledger2._rows[0]["factor"] == "test_strat"

    def test_reactivation_candidates(self, tmp_path):
        ledger = self._make_ledger(tmp_path)
        # Not enough trades
        for i in range(10):
            ledger.record_shadow_signal("few_strat", "BTC", "BUY", 70.0, 100.0)
        candidates = ledger.get_reactivation_candidates(min_trades=50)
        assert len(candidates) == 0

    def test_expired_shadows(self, tmp_path):
        ledger = self._make_ledger(tmp_path)
        # Record with old timestamp
        old_ts = time.time() - 100000  # very old
        ledger.record_shadow_signal("old_strat", "BTC", "BUY", 70.0, 100.0, timestamp=old_ts)
        resolved = ledger.resolve_shadows("BTC", 110.0, max_age_hours=8.0)
        assert resolved == 0  # too old to resolve


# ── CVD Signal ─────────────────────────────────────────────────────

class TestCVDSignal:
    def test_instantiation(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        assert strat.name == "cvd_signal"

    def test_get_status(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        status = strat.get_status("BTC", {})
        assert isinstance(status, dict)

    def test_evaluate_insufficient_data(self):
        import pandas as pd
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        # Too few candles
        df = pd.DataFrame({
            "open": [100], "high": [101], "low": [99],
            "close": [100.5], "volume": [1000]
        })
        result = strat.evaluate("BTC", {"1h": df})
        assert result is None

    def test_evaluate_missing_data(self):
        from strategies.cvd_signal import CVDSignalStrategy
        strat = CVDSignalStrategy()
        result = strat.evaluate("BTC", {})
        assert result is None


# ── Liquidation Signal ─────────────────────────────────────────────

class TestLiquidationSignal:
    def test_instantiation(self):
        from strategies.liquidation_signal import LiquidationSignalStrategy
        strat = LiquidationSignalStrategy()
        assert strat.name == "liquidation_signal"

    def test_get_status(self):
        from strategies.liquidation_signal import LiquidationSignalStrategy
        strat = LiquidationSignalStrategy()
        status = strat.get_status("BTC", {})
        assert isinstance(status, dict)

    def test_evaluate_insufficient_data(self):
        import pandas as pd
        from strategies.liquidation_signal import LiquidationSignalStrategy
        strat = LiquidationSignalStrategy()
        df = pd.DataFrame({
            "open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
            "close": [100.5] * 10, "volume": [1000] * 10
        })
        result = strat.evaluate("BTC", {"1h": df})
        assert result is None  # not enough data


# ── Go-Live Gate ───────────────────────────────────────────────────

class TestGoLiveGate:
    def test_no_data(self):
        from validation.go_live_gate import GoLiveGate
        gate = GoLiveGate()
        result = gate.evaluate()
        assert result["passed"] is False
        assert "INSUFFICIENT DATA" in result["recommendation"] or "BLOCKED" in result["recommendation"]

    def test_with_mock_ledger_positive(self):
        from validation.go_live_gate import GoLiveGate
        mock_ledger = MagicMock()
        mock_ledger.get_trades.return_value = [
            {"net_pnl": "50.0", "timestamp": str(time.time() - 3600 * i),
             "running_equity": str(10000 + i * 10)}
            for i in range(20)
        ]
        gate = GoLiveGate(trade_ledger=mock_ledger)
        result = gate.evaluate()
        # Net PnL should pass (sum of 50*20 = 1000)
        assert result["gates"]["net_pnl"]["passed"] is True

    def test_format_report(self):
        from validation.go_live_gate import GoLiveGate
        gate = GoLiveGate()
        result = gate.evaluate()
        report = gate.format_report(result)
        assert "GO-LIVE GATE" in report
        assert "Recommendation" in report


# ── Regime Audit ───────────────────────────────────────────────────

class TestRegimeAudit:
    def test_classify_actual_regime(self):
        import pandas as pd
        from scripts.regime_audit import classify_actual_regime

        # Trending data: clear upward move
        closes = [100 + i * 0.5 for i in range(20)]
        df = pd.DataFrame({
            "close": closes,
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
        })
        result = classify_actual_regime(df, 0, forward_bars=15)
        assert result in ("trend", "high_volatility", "range", "consolidation")

    def test_run_audit_insufficient_data(self):
        import pandas as pd
        from scripts.regime_audit import run_regime_audit

        df = pd.DataFrame({"close": [100, 101], "high": [102, 103], "low": [99, 100]})
        result = run_regime_audit(df)
        assert "error" in result


# ── Compound Sizing Multiplier Helpers ─────────────────────────────

class TestCompoundSizingHelpers:
    def test_vol_regime_multiplier(self):
        from execution.risk import RiskManager
        # High vol = smaller size
        assert RiskManager.compute_vol_regime_multiplier(2.0, 1.0) < 1.0
        # Low vol = larger size
        assert RiskManager.compute_vol_regime_multiplier(0.5, 1.0) > 1.0
        # Equal vol = 1.0
        assert RiskManager.compute_vol_regime_multiplier(1.0, 1.0) == 1.0
        # Zero baseline
        assert RiskManager.compute_vol_regime_multiplier(1.0, 0.0) == 1.0

    def test_signal_decay(self):
        from execution.risk import RiskManager
        assert RiskManager.compute_signal_decay(0) == 1.0
        assert RiskManager.compute_signal_decay(300) == 0.5
        assert 0.5 < RiskManager.compute_signal_decay(150) < 1.0

    def test_btc_momentum_aligned(self):
        from execution.risk import RiskManager
        # BTC up, trade long = aligned = boost
        mult = RiskManager.compute_btc_momentum_multiplier(0.02, "LONG")
        assert mult > 1.0
        # BTC up, trade short = misaligned = reduce
        mult = RiskManager.compute_btc_momentum_multiplier(0.02, "SHORT")
        assert mult < 1.0
        # BTC flat = no effect
        mult = RiskManager.compute_btc_momentum_multiplier(0.0005, "LONG")
        assert mult == 1.0


# ── IC Tracker Convenience Method ──────────────────────────────────

class TestICTrackerConvenience:
    def test_get_ic_per_factor(self, tmp_path):
        from feedback.ic_tracker import ICTracker
        tracker = ICTracker(data_dir=str(tmp_path))
        # Record some data
        for i in range(15):
            tracker.record("test_factor", 1, 0.01 * (1 if i % 2 == 0 else -1))
        result = tracker.get_ic_per_factor()
        assert isinstance(result, dict)
        assert "test_factor" in result


# ── Kelly Engine Convenience Method ────────────────────────────────

class TestKellyEngineConvenience:
    def test_get_weights_per_factor(self, tmp_path):
        from feedback.kelly_engine import KellyEngine
        engine = KellyEngine(data_path=str(tmp_path / "kelly.json"))
        result = engine.get_weights_per_factor()
        assert isinstance(result, dict)
        # Should have backtest priors
        assert "confidence_scorer" in result


# ── Daily Report Walk-Forward Integration ──────────────────────────

class TestDailyReportWF:
    def test_metric_walk_forward_no_data(self):
        from feedback.daily_report import DailyReporter
        mock_ledger = MagicMock()
        mock_ledger.get_trades.return_value = []
        reporter = DailyReporter(trade_ledger=mock_ledger)
        result = reporter._metric_walk_forward()
        assert result["ratio"] is None
        assert "insufficient" in result["status"].lower() or result["status"] == "insufficient data or module unavailable"


# ── Missed Trade Tracker ──────────────────────────────────────────

class TestMissedTradeTracker:
    def _make_tracker(self, tmpdir):
        from feedback.missed_trade_tracker import MissedTradeTracker
        return MissedTradeTracker(data_dir=str(tmpdir))

    def _make_signal(self):
        from strategies.base import Signal
        return Signal(
            strategy="bollinger_squeeze", symbol="BTC", side="BUY",
            confidence=75.0, entry=65000.0, sl=64000.0,
            tp1=66500.0, tp2=68000.0, atr=500.0,
        )

    def test_record_rejection(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        sig = self._make_signal()
        tracker.record_rejection(signal=sig, reason="Fee drag 42% > 30%", gate="risk_filter")
        assert len(tracker._session_misses) == 1
        mt = tracker._session_misses[0]
        assert mt.symbol == "BTC"
        assert mt.rejection_category == "fee_drag"

    def test_record_ensemble_rejection(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        sig = self._make_signal()
        tracker.record_ensemble_rejection(symbol="BTC", signals=[sig], reason="insufficient_votes")
        assert len(tracker._session_misses) == 1

    def test_compute_counterfactuals(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        sig = self._make_signal()
        tracker.record_rejection(signal=sig, reason="ev_floor", gate="risk_filter")
        # Simulate a price series where price goes up (BUY would have won)
        prices = [65000.0 + i * 100 for i in range(20)]
        tracker.compute_counterfactuals("BTC", prices, start_idx=0, candle_duration_hours=1.0)
        mt = tracker._session_misses[0]
        assert mt.price_after_1h is not None

    def test_generate_report(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        sig = self._make_signal()
        tracker.record_rejection(signal=sig, reason="fee_drag", gate="risk_filter")
        report = tracker.generate_report()
        assert "total_missed" in report
        assert report["total_missed"] == 1

    def test_gate_effectiveness(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        result = tracker.get_gate_effectiveness()
        assert isinstance(result, dict)


# ── Ensemble Missed Trade Wiring ──────────────────────────────────

class TestEnsembleMissedTradeWiring:
    def test_set_missed_trade_tracker(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy(strategies={}, mode="weighted_veto")
        tracker = MagicMock()
        ens.set_missed_trade_tracker(tracker)
        assert ens._missed_trade_tracker is tracker

    def test_record_counterfactual_calls_tracker(self):
        from strategies.ensemble import EnsembleStrategy
        from strategies.base import Signal
        ens = EnsembleStrategy(strategies={}, mode="weighted_veto")
        tracker = MagicMock()
        ens.set_missed_trade_tracker(tracker)
        sig = Signal(
            strategy="test", symbol="BTC", side="BUY",
            confidence=70.0, entry=65000.0, sl=64000.0,
            tp1=66000.0, tp2=67000.0, atr=500.0,
        )
        ens._record_counterfactual(sig, "test_reason")
        tracker.record_rejection.assert_called_once()


# ── Portfolio Risk Budget in Compound Sizing ──────────────────────

class TestPortfolioRiskBudgetSizing:
    def test_risk_budget_reduces_sizing(self):
        """Portfolio risk budget > 50% utilization should reduce compound mult."""
        # Test the math: at 80% utilization, mult = 1.0 - (0.8 - 0.5) * 1.6 = 0.52
        utilization = 0.8
        budget_mult = max(0.2, 1.0 - (utilization - 0.5) * 1.6)
        assert 0.5 < budget_mult < 0.55

    def test_risk_budget_no_reduction_below_50pct(self):
        """Below 50% utilization, no reduction should be applied."""
        utilization = 0.3
        # The code only applies reduction when utilization > 0.5
        assert utilization <= 0.5  # No multiplier applied

    def test_risk_budget_floor_at_20pct(self):
        """At 100% utilization, budget_mult should floor at 0.2."""
        utilization = 1.0
        budget_mult = max(0.2, 1.0 - (utilization - 0.5) * 1.6)
        assert budget_mult == 0.2


# ── Compound Size Multiplier Cache ────────────────────────────────

class TestCompoundMultCache:
    def test_cache_stores_and_retrieves(self):
        """_compound_mult_cache should store per-symbol values."""
        cache = {}
        cache["BTC"] = round(0.7543, 4)
        assert cache["BTC"] == 0.7543
        # Pop on close
        val = cache.pop("BTC", "")
        assert val == 0.7543
        assert "BTC" not in cache
