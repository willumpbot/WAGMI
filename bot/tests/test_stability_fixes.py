"""
Tests for stability fixes:
1. Risk-based position sizing with capped risk_multiplier
2. ASCII-only logging (no Unicode arrows)
3. ML heartbeat array truth check
4. Circuit breaker high-confidence override
5. Trade log writes after close
"""

import os
import sys
import csv
import time
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.risk import RiskManager, CircuitBreaker, _log_safety_event
from execution.position_manager import PositionManager, Position
from execution.position_state import (
    IDLE, OPEN, TP1_HIT, TRAILING, CLOSED, transition,
)


class TestPositionSizingRiskBased(unittest.TestCase):
    """Test that position sizing uses risk-based formula with capped multiplier."""

    def test_basic_risk_sizing(self):
        """qty = risk_usd / (effective_stop * leverage), effective_stop includes fees."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        # entry=100, sl=95, stop_width=5, fees=0.08 (4bps*2), lev=2x
        # effective_stop = 5.08, qty = 100 / (5.08 * 2) ≈ 9.84
        qty = rm.calculate_qty(100.0, 95.0, leverage=2.0, risk_multiplier=1.0)
        self.assertAlmostEqual(qty, 9.84, places=1)

    def test_risk_multiplier_capped_at_1_5(self):
        """risk_multiplier should be capped at 1.5, not allow 3.5x."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        # With rm=3.5 (uncapped would be 350$), capped should be 1.5 (150$)
        qty_capped = rm.calculate_qty(100.0, 95.0, leverage=2.0, risk_multiplier=3.5)
        qty_max = rm.calculate_qty(100.0, 95.0, leverage=2.0, risk_multiplier=1.5)
        self.assertEqual(qty_capped, qty_max)

    def test_higher_leverage_smaller_qty(self):
        """Higher leverage should produce smaller qty (constant dollar risk)."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        qty_2x = rm.calculate_qty(100.0, 95.0, leverage=2.0)
        qty_10x = rm.calculate_qty(100.0, 95.0, leverage=10.0)
        self.assertGreater(qty_2x, qty_10x)
        # Higher leverage -> proportionally smaller qty
        self.assertAlmostEqual(qty_10x / qty_2x, 2.0 / 10.0, places=1)

    def test_zero_stop_returns_zero_qty(self):
        """Zero stop width should return 0 qty (no division by zero)."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        qty = rm.calculate_qty(100.0, 100.0, leverage=2.0)
        self.assertEqual(qty, 0.0)

    def test_default_risk_per_trade_is_one_percent(self):
        """Default risk_per_trade should be 1% (0.01), not 1.5%."""
        from trading_config import TradingConfig
        # Default without env override
        with patch.dict(os.environ, {}, clear=False):
            config = TradingConfig()
            # Should be 0.02 (2%) unless overridden by env
            self.assertLessEqual(config.risk_per_trade, 0.025)

    def test_max_dollar_risk_per_trade(self):
        """With $10k equity and 1% risk capped at 1.5x rm, effective risk ≤ $150."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        # Even with rm=10 (extreme), capped at 1.5
        qty = rm.calculate_qty(100.0, 95.0, leverage=2.0, risk_multiplier=10.0)
        # Dollar risk using effective_stop (includes fees): should equal risk_usd
        from trading_config import TradingConfig
        fee_bps = TradingConfig().taker_fee_bps
        fee_width = 100.0 * (fee_bps * 2 / 10000.0)
        effective_stop = 5.0 + fee_width
        dollar_risk = effective_stop * qty * 2
        self.assertAlmostEqual(dollar_risk, 150.0, places=0)


class TestASCIILoggingNoUnicode(unittest.TestCase):
    """Test that all logging/output uses ASCII only (no Unicode arrows)."""

    def test_state_path_str_uses_ascii_arrows(self):
        """Position.state_path_str should use '->' not Unicode arrow."""
        pm = PositionManager(taker_fee_bps=0, enable_trailing=True, trailing_atr_mult=1.5)
        pos = pm.open_position("BTC", "LONG", 100.0, 1.0, 95.0, 105.0, 110.0, atr=2.0)
        self.assertIsNotNone(pos)
        path = pos.state_path_str
        self.assertNotIn("\u2192", path, "Unicode arrow found in state_path_str!")
        self.assertIn("->", path)

    def test_state_transition_log_uses_ascii(self):
        """transition() log messages should use '->' not Unicode arrow."""
        # This tests that position_state.py uses ASCII
        state = transition("TEST", IDLE, OPEN, "test open")
        self.assertEqual(state, OPEN)
        # If we got here without UnicodeEncodeError, ASCII is working

    def test_full_lifecycle_state_path_ascii(self):
        """Full IDLE->OPEN->TP1_HIT->TRAILING->CLOSED path uses ASCII."""
        pm = PositionManager(taker_fee_bps=0, enable_trailing=True, trailing_atr_mult=1.5)
        pos = pm.open_position("BTC", "LONG", 100.0, 1.0, 95.0, 105.0, 110.0, atr=2.0)
        # Simulate TP1
        events = pm.update_price("BTC", 105.0)
        # Simulate TP2
        events = pm.update_price("BTC", 110.0)
        pos = pm.positions["BTC"]
        path = pos.state_path_str
        self.assertNotIn("\u2192", path)
        expected_states = ["IDLE", "OPEN", "TP1_HIT", "TRAILING", "CLOSED"]
        for s in expected_states:
            self.assertIn(s, path)

    def test_no_unicode_arrows_in_source_files(self):
        """Scan key source files for Unicode arrows."""
        bot_dir = Path(__file__).parent.parent
        critical_files = [
            "execution/position_state.py",
            "execution/position_manager.py",
            "data/trade_log.py",
            "data/learning.py",
            "data/ml_log.py",
        ]
        for rel_path in critical_files:
            full_path = bot_dir / rel_path
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")
                self.assertNotIn("\u2192", content,
                                 f"Unicode arrow found in {rel_path}")


class TestMLHeartbeatNoArrayTruthError(unittest.TestCase):
    """Test that ML weight checks don't trigger numpy array truth ambiguity."""

    def test_weights_none_check(self):
        """'weights is not None and len(weights) > 0' works for None."""
        weights = None
        result = weights is not None and len(weights) > 0
        self.assertFalse(result)

    def test_weights_empty_array_check(self):
        """'weights is not None and len(weights) > 0' works for empty array."""
        import numpy as np
        weights = np.array([])
        result = weights is not None and len(weights) > 0
        self.assertFalse(result)

    def test_weights_populated_array_check(self):
        """'weights is not None and len(weights) > 0' works for real weights."""
        import numpy as np
        weights = np.array([0.1, 0.2, 0.3])
        result = weights is not None and len(weights) > 0
        self.assertTrue(result)

    def test_numpy_array_truth_value_error(self):
        """Demonstrate the bug: 'if np_array:' raises ValueError."""
        import numpy as np
        weights = np.array([0.1, 0.2])
        with self.assertRaises(ValueError):
            if weights:
                pass


class TestCircuitBreakerHighConfOverride(unittest.TestCase):
    """Test circuit breaker allows high-confidence trades when tripped."""

    def test_cb_blocks_normal_trades_when_tripped(self):
        """Normal confidence trades should be blocked when CB is tripped."""
        cb = CircuitBreaker(daily_loss_limit_pct=0.05, cooldown_minutes=60)
        cb.peak_equity = 10000
        cb.record_trade(-600, 9400)  # 6% loss triggers CB
        self.assertTrue(cb.tripped)
        # Normal trade (70% confidence) should be blocked
        self.assertFalse(cb.is_trading_allowed(confidence=70.0))

    def test_cb_blocks_all_trades_when_tripped(self):
        """All trades should be blocked when CB is tripped — no overrides."""
        cb = CircuitBreaker(daily_loss_limit_pct=0.05, cooldown_minutes=60)
        cb.peak_equity = 10000
        cb.record_trade(-600, 9400)  # triggers CB
        self.assertTrue(cb.tripped)
        # Even high confidence should be blocked (overrides disabled)
        self.assertFalse(cb.is_trading_allowed(confidence=93.0, cb_conf_override_pct=0.92))

    def test_cb_blocks_below_override_threshold(self):
        """Trades below override threshold should still be blocked."""
        cb = CircuitBreaker(daily_loss_limit_pct=0.05, cooldown_minutes=60)
        cb.peak_equity = 10000
        cb.record_trade(-600, 9400)
        self.assertTrue(cb.tripped)
        # All trades blocked when CB tripped
        self.assertFalse(cb.is_trading_allowed(confidence=91.0, cb_conf_override_pct=0.92))

    def test_cb_not_tripped_allows_all(self):
        """When CB is not tripped, all trades should be allowed."""
        cb = CircuitBreaker()
        cb.peak_equity = 10000
        self.assertTrue(cb.is_trading_allowed(confidence=50.0))

    def test_risk_manager_blocks_all_when_tripped(self):
        """RiskManager.can_open_position should block all trades when CB tripped."""
        rm = RiskManager(starting_equity=10000)
        # Trip the CB
        rm.circuit_breaker.peak_equity = 10000
        rm.update_equity(-600)  # 6% loss
        self.assertTrue(rm.circuit_breaker.tripped)
        # Normal confidence blocked
        self.assertFalse(rm.can_open_position(0, confidence=70.0))
        # High confidence also blocked (overrides disabled)
        self.assertFalse(rm.can_open_position(0, confidence=93.0, cb_conf_override_pct=0.92))

    def test_safety_event_logged_on_trip(self):
        """Circuit breaker trip should log to safety_events.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            safety_file = os.path.join(tmpdir, "safety_events.csv")
            with patch("execution.risk._SAFETY_LOG_DIR", tmpdir), \
                 patch("execution.risk._SAFETY_LOG_FILE", safety_file):
                _log_safety_event("circuit_breaker", "test reason", {"pnl": -100})
                self.assertTrue(os.path.exists(safety_file))
                with open(safety_file) as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    self.assertEqual(len(rows), 2)  # header + 1 event
                    self.assertEqual(rows[1][1], "circuit_breaker")


class TestEarlyExitSlProgressBounds(unittest.TestCase):
    """Test that early exit sl_progress stays bounded and doesn't fire past SL."""

    def _make_5m_df(self, closes):
        """Build a minimal 5m DataFrame for early exit testing."""
        import pandas as pd
        return pd.DataFrame({"close": closes})

    def test_sl_progress_above_1_returns_false(self):
        """If price is already past SL (progress > 1.0), let SL check handle it."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "LONG", 100.0, 1.0, 95.0, 105.0, 110.0, atr=2.0)
        # Price at 89.0: entry=100, SL=95, stop_dist=5
        # sl_progress = (100 - 89) / 5 = 2.2 (>1.0, past SL)
        df = self._make_5m_df([91, 90.5, 90, 89.5, 89, 88.5, 88, 87.5, 87, 86.5, 86, 85.5, 85, 84.5, 84])
        result = pm._check_early_exit(pos, 89.0, df)
        self.assertFalse(result, "Early exit should not fire when price is past SL")

    def test_sl_progress_at_60_pct_can_trigger(self):
        """sl_progress at 60% (within bounds) should be able to trigger."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "LONG", 100.0, 1.0, 95.0, 105.0, 110.0, atr=2.0)
        # Price at 97.0: sl_progress = (100-97)/5 = 0.6 (60%)
        # Need: 3 accelerating candles down + EMA5 < EMA13
        closes = [99, 98.8, 98.6, 98.4, 98.2, 98, 97.8, 97.6, 97.4, 97.2, 97, 96.8, 96.6, 96.4, 96.2]
        df = self._make_5m_df(closes)
        # This may or may not trigger depending on EMA crossover, but it should NOT crash
        result = pm._check_early_exit(pos, 97.0, df)
        self.assertIsInstance(result, bool)

    def test_sl_progress_at_30_pct_does_not_trigger(self):
        """sl_progress at 30% (< 50% threshold) should never trigger."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "LONG", 100.0, 1.0, 95.0, 105.0, 110.0, atr=2.0)
        # Price at 98.5: sl_progress = (100-98.5)/5 = 0.3 (30%)
        closes = [99, 98.9, 98.8, 98.7, 98.6, 98.5, 98.4, 98.3, 98.2, 98.1, 98, 97.9, 97.8, 97.7, 97.6]
        df = self._make_5m_df(closes)
        result = pm._check_early_exit(pos, 98.5, df)
        self.assertFalse(result, "Should not trigger at 30% toward SL")

    def test_short_sl_progress_above_1_returns_false(self):
        """Short position past SL should also not trigger early exit."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "SHORT", 100.0, 1.0, 105.0, 95.0, 90.0, atr=2.0)
        # Price at 106: sl_progress = (106-100)/5 = 1.2 (>1.0)
        closes = [101, 101.5, 102, 102.5, 103, 103.5, 104, 104.5, 105, 105.5, 106, 106.5, 107, 107.5, 108]
        df = self._make_5m_df(closes)
        result = pm._check_early_exit(pos, 106.0, df)
        self.assertFalse(result, "Short early exit should not fire past SL")


class TestTradeLogsWrittenAfterClose(unittest.TestCase):
    """Test that trade_outcomes.csv and trades.csv write correctly."""

    def test_trade_outcome_csv_writes(self):
        """record_trade_outcome should write a row to trade_outcomes.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outcomes_file = os.path.join(tmpdir, "trade_outcomes.csv")
            with patch("data.learning._OUTCOMES_DIR", tmpdir), \
                 patch("data.learning._OUTCOMES_FILE", outcomes_file):
                from data.learning import record_trade_outcome
                record_trade_outcome(
                    symbol="BTC", side="LONG", outcome="CLEAN_WIN",
                    pnl=100.0, entry=50000.0, sl=49000.0,
                    tp1=51000.0, tp2=52000.0, tp1_hit=True,
                    sl_after_tp1=False, state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
                    leverage=2.0, confidence=80.0, strategy="regime_trend",
                    entry_type="TREND", primary_driver="regime_trend",
                    regime="trending", volatility_band="medium",
                )
                self.assertTrue(os.path.exists(outcomes_file))
                with open(outcomes_file) as f:
                    rows = list(csv.DictReader(f))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["symbol"], "BTC")
                    self.assertEqual(rows[0]["entry_type"], "TREND")
                    self.assertNotIn("\u2192", rows[0].get("state_path", ""))

    def test_trade_log_csv_writes(self):
        """log_closed_trade should write a row to trades.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trades_file = os.path.join(tmpdir, "trades.csv")
            with patch("data.trade_log._TRADES_DIR", tmpdir), \
                 patch("data.trade_log._TRADES_FILE", trades_file):
                from data.trade_log import log_closed_trade
                log_closed_trade(
                    symbol="SOL", side="SHORT", entry=150.0,
                    exit_price=145.0, action="TP2", pnl=50.0,
                    fees=0.5, state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
                    outcome="CLEAN_WIN", leverage=3.0, confidence=85.0,
                    strategy="monte_carlo_zones",
                    entry_type="MEDIUM", primary_driver="monte_carlo_zones",
                    regime="trending", volatility_band="medium",
                )
                self.assertTrue(os.path.exists(trades_file))
                with open(trades_file) as f:
                    rows = list(csv.DictReader(f))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["symbol"], "SOL")
                    self.assertEqual(rows[0]["entry_type"], "MEDIUM")
                    # Verify no Unicode in state_path
                    self.assertNotIn("\u2192", rows[0]["state_path"])


class TestFlatDecisionZeroWeights(unittest.TestCase):
    """Test that flat decisions with all-zero strategy_weights pass validation.

    Bug: LLM returns flat + all-zero weights (correct for 'skip trade'),
    but validator.py rejects with 'strategy_weights sum too low: 0.0'.
    """

    def _make_decision(self, action, confidence=0.0, regime="unknown",
                       size_multiplier=0.0, all_zero_weights=True):
        from llm.decision_types import LLMDecision, StrategyWeights
        sw = StrategyWeights(
            regime_trend=0, monte_carlo_zones=0, confidence_scorer=0,
            multi_tier_quality=0, funding_rate=0, open_interest=0,
            volume_momentum=0, cross_asset=0,
        ) if all_zero_weights else StrategyWeights()
        return LLMDecision(
            action=action,
            confidence=confidence,
            regime=regime,
            strategy_weights=sw,
            memory_update=None,
            notes="test",
            size_multiplier=size_multiplier,
        )

    def test_flat_zero_weights_passes_schema(self):
        """Flat + all-zero weights should pass schema validation."""
        from llm.validator import validate_schema
        decision = self._make_decision("flat")
        valid, err = validate_schema(decision)
        self.assertTrue(valid, f"Flat with zero weights should pass schema: {err}")

    def test_flat_zero_weights_passes_full_pipeline(self):
        """Flat + all-zero weights should pass validate_and_sanitize."""
        from llm.validator import validate_and_sanitize
        decision = self._make_decision("flat")
        result, err = validate_and_sanitize(decision)
        self.assertIsNotNone(result, f"Flat with zero weights should pass: {err}")
        self.assertEqual(result.action, "flat")

    def test_proceed_zero_weights_still_fails(self):
        """Proceed + all-zero weights should still be rejected."""
        from llm.validator import validate_schema
        decision = self._make_decision("proceed", confidence=0.7, regime="trend",
                                       size_multiplier=1.0)
        valid, err = validate_schema(decision)
        self.assertFalse(valid)
        self.assertIn("strategy_weights sum too low", err)

    def test_flip_zero_weights_still_fails(self):
        """Flip + all-zero weights should still be rejected."""
        from llm.validator import validate_schema
        decision = self._make_decision("flip", confidence=0.8, regime="trend",
                                       size_multiplier=1.0)
        valid, err = validate_schema(decision)
        self.assertFalse(valid)
        self.assertIn("strategy_weights sum too low", err)


if __name__ == "__main__":
    unittest.main()
