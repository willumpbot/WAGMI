"""
Tests for ConvictionSizer — conviction-based leverage and position sizing.

Tests verify directional behavior (higher confluence = higher leverage, modifiers
work correctly) using range assertions rather than exact values, since modifiers
like time-of-day can shift values.
"""

import os
import sys
import tempfile
import unittest

# Ensure bot/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from manual.conviction_sizer import (
    ConvictionSizer,
    ConvictionResult,
    size_from_entry_map_record,
    CONFLUENCE_LEVERAGE,
    CONFLUENCE_RISK_PCT,
    PRECISION_CONFLUENCE_LEVERAGE,
    PRECISION_RISK_PCT,
    _tier_name,
)


# ── Helpers ──────────────────────────────────────────────────────────────
# HYPE noise floor is 0.98%, so stop must be >= 0.98% of entry.
# entry=39.28, SL=38.88 => stop width = 0.40/39.28 = 1.019% (passes)
# SOL noise floor is 0.66%, so stop must be >= 0.66% of entry.
# entry=83.03, SL=83.60 (SELL) => stop width = 0.57/83.03 = 0.687% (passes)

HYPE_ENTRY = 39.28
HYPE_SL = 38.88       # 1.02% stop width — above 0.98% noise floor
HYPE_TP = 40.08
HYPE_STOP_WIDTH = HYPE_ENTRY - HYPE_SL  # 0.40

SOL_ENTRY = 83.03
SOL_SL_SELL = 83.60    # 0.69% stop width — above 0.66% noise floor
SOL_TP_SELL = 81.79


class TestConvictionSizerBasicLeverage(unittest.TestCase):
    """Test that base leverage maps correctly from confluence count."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_conviction.jsonl")
        self.sizer = ConvictionSizer(log_path=self.log_path)

    def _base_params(self, confluences=3):
        return dict(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=confluences,
            confluence_sources=["BB_Mid", "EMA20", "EMA50"],
            symbol="HYPE",
            side="BUY",
            utc_hour=12,  # Non-prime hours, no modifier
        )

    def test_1_confluence_5x(self):
        result = self.sizer.size(**self._base_params(confluences=1))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 5.0)
        # No modifiers at noon UTC, no streak, no alignment
        self.assertAlmostEqual(result.leverage, 5.0, places=1)

    def test_2_confluences_8x(self):
        result = self.sizer.size(**self._base_params(confluences=2))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 8.0)

    def test_3_confluences_10x(self):
        result = self.sizer.size(**self._base_params(confluences=3))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 10.0)

    def test_4_confluences_12x(self):
        result = self.sizer.size(**self._base_params(confluences=4))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 12.0)

    def test_5_confluences_15x(self):
        result = self.sizer.size(**self._base_params(confluences=5))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 15.0)

    def test_6_confluences_capped_at_5(self):
        """6+ confluences should use the 5-tier (15x base)."""
        result = self.sizer.size(**self._base_params(confluences=6))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 15.0)

    def test_0_confluences_clamped_to_1(self):
        """0 confluences should clamp to 1."""
        result = self.sizer.size(**self._base_params(confluences=0))
        self.assertIsNotNone(result)
        self.assertEqual(result.base_leverage, 5.0)

    def test_higher_confluence_higher_leverage(self):
        """More confluences should always produce >= leverage."""
        prev_lev = 0
        for conf in [1, 2, 3, 4, 5]:
            result = self.sizer.size(**self._base_params(confluences=conf))
            self.assertIsNotNone(result)
            self.assertGreaterEqual(result.leverage, prev_lev)
            prev_lev = result.leverage


class TestConvictionSizerRiskPct(unittest.TestCase):
    """Test that risk % scales with confluence count."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def _params(self, confluences):
        return dict(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=confluences,
            symbol="HYPE",
            side="BUY",
            utc_hour=12,
        )

    def test_1_conf_1pct_risk(self):
        result = self.sizer.size(**self._params(1))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.risk_pct, 0.010, places=3)

    def test_2_conf_1pct_risk(self):
        result = self.sizer.size(**self._params(2))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.risk_pct, 0.010, places=3)

    def test_3_conf_1_5pct_risk(self):
        result = self.sizer.size(**self._params(3))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.risk_pct, 0.015, places=3)

    def test_4_conf_2pct_risk(self):
        result = self.sizer.size(**self._params(4))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.risk_pct, 0.020, places=3)

    def test_5_conf_2_5pct_risk(self):
        result = self.sizer.size(**self._params(5))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.risk_pct, 0.025, places=3)

    def test_risk_increases_with_confluence(self):
        """Higher confluence should give >= risk percentage."""
        prev_risk = 0
        for conf in [1, 2, 3, 4, 5]:
            result = self.sizer.size(**self._params(conf))
            self.assertIsNotNone(result)
            self.assertGreaterEqual(result.risk_pct, prev_risk)
            prev_risk = result.risk_pct


class TestConvictionSizerModifiers(unittest.TestCase):
    """Test leverage modifiers (time, vol, alignment, counter-trend, streaks)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def _params(self, **overrides):
        base = dict(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=3,
            symbol="HYPE",
            side="BUY",
            utc_hour=12,  # non-prime
        )
        base.update(overrides)
        return base

    def test_prime_hours_boost(self):
        """UTC 20 = prime hours, should get +10% leverage."""
        result_prime = self.sizer.size(**self._params(utc_hour=20))
        result_normal = self.sizer.size(**self._params(utc_hour=12))
        self.assertGreater(result_prime.leverage, result_normal.leverage)
        any_prime = any("prime_hours" in m for m in result_prime.modifiers_applied)
        self.assertTrue(any_prime)

    def test_multi_tf_aligned_boost(self):
        """Multi-TF alignment should give +20% leverage."""
        result_aligned = self.sizer.size(**self._params(multi_tf_aligned=True))
        result_normal = self.sizer.size(**self._params(multi_tf_aligned=False))
        self.assertGreater(result_aligned.leverage, result_normal.leverage)

    def test_optimal_vol_regime_boost(self):
        """HYPE in optimal vol band (1.40-1.69%) should get +10%."""
        # ATR/price = 0.60/39.28 = ~1.53% -> in optimal band
        result_optimal = self.sizer.size(**self._params(atr=0.60))
        result_normal = self.sizer.size(**self._params(atr=None))
        self.assertGreater(result_optimal.leverage, result_normal.leverage)

    def test_counter_trend_penalty(self):
        """SELL in trending_bull regime should get -50%."""
        result = self.sizer.size(**self._params(
            side="SELL", regime="trending_bull",
            sl_price=SOL_SL_SELL, tp_price=SOL_TP_SELL,
            entry_price=SOL_ENTRY, symbol="SOL",
        ))
        self.assertIsNotNone(result)
        # Base 10x * 0.50 = 5x
        self.assertLessEqual(result.leverage, 6.0)
        any_counter = any("counter_trend" in m for m in result.modifiers_applied)
        self.assertTrue(any_counter)

    def test_win_streak_boost(self):
        """2+ consecutive wins should give +15% leverage."""
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(True)
        result = self.sizer.size(**self._params())
        any_win = any("win_streak" in m for m in result.modifiers_applied)
        self.assertTrue(any_win)
        # 10x * 1.15 = 11.5x
        self.assertGreaterEqual(result.leverage, 11.0)

    def test_loss_streak_penalty(self):
        """2+ consecutive losses should give -30% leverage."""
        self.sizer.record_outcome(False)
        self.sizer.record_outcome(False)
        result = self.sizer.size(**self._params())
        any_loss = any("loss_streak" in m for m in result.modifiers_applied)
        self.assertTrue(any_loss)
        # 10x * 0.70 = 7.0x
        self.assertLessEqual(result.leverage, 7.5)

    def test_all_modifiers_stacked(self):
        """All positive modifiers stacked: multi_tf + prime + vol + win streak."""
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(True)
        result = self.sizer.size(**self._params(
            confluences=5,
            multi_tf_aligned=True,
            utc_hour=22,    # prime
            atr=0.60,       # optimal vol
        ))
        # Base 15x * 1.20 * 1.10 * 1.10 * 1.15 = ~25.0x -> capped at 20x
        self.assertEqual(result.leverage, 20.0)  # Max cap


class TestConvictionSizerMath(unittest.TestCase):
    """Test the specific HYPE BUY example from the spec."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def test_hype_buy_5_confluences_example(self):
        """
        HYPE BUY at entry, 5 confluences, $89 account.
        Expected: 15x leverage, 2.5% risk.
        """
        result = self.sizer.size(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=5,
            confluence_sources=["BB_Mid", "EMA20", "EMA50", "VWAP", "Fib_618"],
            symbol="HYPE",
            side="BUY",
            utc_hour=12,  # non-prime to test base
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.conviction_tier, "fortress")
        self.assertEqual(result.base_leverage, 15.0)
        self.assertEqual(result.leverage, 15.0)
        self.assertAlmostEqual(result.risk_pct, 0.025, places=3)

        # Risk amount: $89 * 0.025 = $2.225
        self.assertAlmostEqual(result.risk_amount, 2.23, delta=0.05)

        # Stop width = entry - SL
        stop_width = HYPE_ENTRY - HYPE_SL
        # qty = risk_amount / stop_width
        expected_qty = 2.225 / stop_width
        # Notional = qty * entry
        self.assertGreater(result.position_notional, 100)

        # R:R = tp_dist / stop_width
        tp_dist = HYPE_TP - HYPE_ENTRY
        expected_rr = tp_dist / stop_width
        self.assertAlmostEqual(result.rr_ratio, expected_rr, delta=0.1)

        # PnL if TP: positive
        self.assertGreater(result.pnl_if_tp, 0)

        # PnL if SL: negative, roughly equal to risk_amount
        self.assertLess(result.pnl_if_sl, 0)
        self.assertAlmostEqual(abs(result.pnl_if_sl), result.risk_amount, delta=0.1)

    def test_sol_sell_4_confluences(self):
        """SOL SELL at $83.03, 4 confluences."""
        result = self.sizer.size(
            equity=89.0,
            entry_price=SOL_ENTRY,
            sl_price=SOL_SL_SELL,
            tp_price=SOL_TP_SELL,
            confluences=4,
            confluence_sources=["BB_Mid", "EMA9", "EMA20", "VWAP"],
            symbol="SOL",
            side="SELL",
            utc_hour=12,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.conviction_tier, "very_strong")
        self.assertEqual(result.base_leverage, 12.0)
        self.assertAlmostEqual(result.risk_pct, 0.020, places=3)


class TestConvictionSizerEdgeCases(unittest.TestCase):
    """Test edge cases and validation."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def test_zero_equity_returns_none(self):
        result = self.sizer.size(
            equity=0, entry_price=HYPE_ENTRY, sl_price=HYPE_SL,
            tp_price=HYPE_TP, confluences=3, symbol="HYPE", side="BUY",
        )
        self.assertIsNone(result)

    def test_zero_entry_returns_none(self):
        result = self.sizer.size(
            equity=89.0, entry_price=0, sl_price=38.98,
            tp_price=40.0, confluences=3, symbol="HYPE", side="BUY",
        )
        self.assertIsNone(result)

    def test_buy_with_sl_above_entry_returns_none(self):
        result = self.sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=39.50,
            tp_price=HYPE_TP, confluences=3, symbol="HYPE", side="BUY",
        )
        self.assertIsNone(result)

    def test_sell_with_sl_below_entry_returns_none(self):
        result = self.sizer.size(
            equity=89.0, entry_price=SOL_ENTRY, sl_price=82.00,
            tp_price=SOL_TP_SELL, confluences=3, symbol="SOL", side="SELL",
        )
        self.assertIsNone(result)

    def test_very_tight_stop_returns_none(self):
        """Stop width below noise floor should be rejected."""
        result = self.sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=39.20,
            tp_price=HYPE_TP, confluences=3, symbol="HYPE", side="BUY",
        )
        # 39.28 - 39.20 = 0.08 / 39.28 = 0.20% < 0.98% noise floor
        self.assertIsNone(result)

    def test_margin_capped_at_equity(self):
        """If notional/leverage exceeds equity, position should be scaled down."""
        result = self.sizer.size(
            equity=10.0,  # tiny account
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=5,
            symbol="HYPE",
            side="BUY",
            utc_hour=12,
        )
        self.assertIsNotNone(result)
        self.assertLessEqual(result.margin_required, 10.0)

    def test_leverage_capped_at_max(self):
        """Even with all modifiers, leverage cannot exceed max_leverage."""
        sizer = ConvictionSizer(max_leverage=10.0, log_path=os.path.join(self.tmp, "test.jsonl"))
        result = sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=HYPE_SL,
            tp_price=HYPE_TP, confluences=5, symbol="HYPE", side="BUY",
            multi_tf_aligned=True, utc_hour=22,
        )
        self.assertIsNotNone(result)
        self.assertLessEqual(result.leverage, 10.0)


class TestConvictionSizerStreakTracking(unittest.TestCase):
    """Test win/loss streak recording and modifier logic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def test_consecutive_wins_count(self):
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(True)
        self.assertEqual(self.sizer.get_consecutive_wins(), 3)
        self.assertEqual(self.sizer.get_consecutive_losses(), 0)

    def test_consecutive_losses_count(self):
        self.sizer.record_outcome(False)
        self.sizer.record_outcome(False)
        self.assertEqual(self.sizer.get_consecutive_losses(), 2)

    def test_streak_broken_by_opposite(self):
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(True)
        self.sizer.record_outcome(False)  # Breaks win streak
        self.assertEqual(self.sizer.get_consecutive_wins(), 0)
        self.assertEqual(self.sizer.get_consecutive_losses(), 1)

    def test_single_outcome_no_streak_modifier(self):
        self.sizer.record_outcome(True)
        self.assertEqual(self.sizer.get_consecutive_wins(), 1)
        mod, desc = self.sizer._get_streak_modifier()
        self.assertEqual(mod, 1.0)


class TestConvictionSizerTierName(unittest.TestCase):
    """Test tier naming."""

    def test_tier_names(self):
        self.assertEqual(_tier_name(1), "minimum")
        self.assertEqual(_tier_name(2), "moderate")
        self.assertEqual(_tier_name(3), "strong")
        self.assertEqual(_tier_name(4), "very_strong")
        self.assertEqual(_tier_name(5), "fortress")
        self.assertEqual(_tier_name(10), "fortress")


class TestConvictionSizerResult(unittest.TestCase):
    """Test ConvictionResult methods."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def test_to_dict(self):
        result = self.sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=HYPE_SL,
            tp_price=HYPE_TP, confluences=3, symbol="HYPE", side="BUY", utc_hour=12,
        )
        self.assertIsNotNone(result)
        d = result.to_dict()
        self.assertIn("leverage", d)
        self.assertIn("confluence_count", d)
        self.assertIn("conviction_tier", d)
        self.assertEqual(d["confluence_count"], 3)

    def test_summary_string(self):
        result = self.sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=HYPE_SL,
            tp_price=HYPE_TP, confluences=5, symbol="HYPE", side="BUY", utc_hour=12,
        )
        self.assertIsNotNone(result)
        summary = result.summary()
        self.assertIn("FORTRESS", summary)
        self.assertIn("5 confluences", summary)
        self.assertIn("15.0x lev", summary)


class TestSizeFromEntryMapRecord(unittest.TestCase):
    """Test the convenience function for entry_map.json records."""

    def test_hype_buy_entry_map_record(self):
        # Use entry/SL values that pass noise floor (>= 0.98% for HYPE)
        record = {
            "symbol": "HYPE",
            "level": HYPE_ENTRY,
            "direction": "BUY",
            "sl": HYPE_SL,
            "tp": HYPE_TP,
            "confluences": 5,
            "confluence_sources": ["BB_Mid", "EMA20", "EMA50", "VWAP", "fib_618"],
            "atr": 0.3941,
            "confidence": 98,
        }
        result = size_from_entry_map_record(
            equity=89.0, record=record, utc_hour=12,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.conviction_tier, "fortress")
        self.assertEqual(result.base_leverage, 15.0)

    def test_sol_sell_entry_map_record(self):
        record = {
            "symbol": "SOL",
            "level": SOL_ENTRY,
            "direction": "SELL",
            "sl": SOL_SL_SELL,
            "tp": SOL_TP_SELL,
            "confluences": 4,
            "confluence_sources": ["BB_Mid", "EMA9", "EMA20", "VWAP"],
            "atr": 0.5665,
            "confidence": 97,
        }
        result = size_from_entry_map_record(
            equity=89.0, record=record, utc_hour=12,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.conviction_tier, "very_strong")


class TestConvictionSizerLogging(unittest.TestCase):
    """Test that sizing decisions are logged."""

    def test_log_file_created(self):
        tmp = tempfile.mkdtemp()
        log_path = os.path.join(tmp, "conviction.jsonl")
        sizer = ConvictionSizer(log_path=log_path)
        sizer.size(
            equity=89.0, entry_price=HYPE_ENTRY, sl_price=HYPE_SL,
            tp_price=HYPE_TP, confluences=3, symbol="HYPE", side="BUY", utc_hour=12,
        )
        self.assertTrue(os.path.exists(log_path))
        import json
        with open(log_path) as f:
            line = f.readline()
        record = json.loads(line)
        self.assertEqual(record["symbol"], "HYPE")
        self.assertEqual(record["confluences"], 3)


class TestCounterTrendDetection(unittest.TestCase):
    """Test counter-trend detection."""

    def test_buy_in_bear_is_counter(self):
        self.assertTrue(ConvictionSizer._is_counter_trend("BUY", "trending_bear"))

    def test_sell_in_bull_is_counter(self):
        self.assertTrue(ConvictionSizer._is_counter_trend("SELL", "trending_bull"))

    def test_sell_in_trend_is_counter(self):
        self.assertTrue(ConvictionSizer._is_counter_trend("SELL", "trend"))

    def test_buy_in_bull_is_not_counter(self):
        self.assertFalse(ConvictionSizer._is_counter_trend("BUY", "trending_bull"))

    def test_buy_in_range_is_not_counter(self):
        self.assertFalse(ConvictionSizer._is_counter_trend("BUY", "range"))

    def test_buy_in_unknown_is_not_counter(self):
        self.assertFalse(ConvictionSizer._is_counter_trend("BUY", "unknown"))


class TestConvictionSizerPrecisionMode(unittest.TestCase):
    """Test precision mode (5m entries) gives higher leverage tiers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer_std = ConvictionSizer(log_path=os.path.join(self.tmp, "std.jsonl"))
        self.sizer_prec = ConvictionSizer(
            precision_mode=True, log_path=os.path.join(self.tmp, "prec.jsonl")
        )

    def _params(self, confluences=3):
        return dict(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=confluences,
            symbol="HYPE",
            side="BUY",
            utc_hour=12,
        )

    def test_precision_higher_base_leverage(self):
        """Precision mode should give higher base leverage at same confluence."""
        for conf in [1, 2, 3, 4, 5]:
            r_std = self.sizer_std.size(**self._params(conf))
            r_prec = self.sizer_prec.size(**self._params(conf))
            self.assertIsNotNone(r_std)
            self.assertIsNotNone(r_prec)
            self.assertGreater(
                r_prec.base_leverage, r_std.base_leverage,
                f"Precision base_leverage should exceed standard at conf={conf}"
            )

    def test_precision_mode_flag_set(self):
        r = self.sizer_prec.size(**self._params(3))
        self.assertIsNotNone(r)
        self.assertTrue(r.precision_mode)

    def test_precision_risk_decreases_with_leverage(self):
        """In precision mode, risk % should decrease as confluence increases.

        This is the key insight: higher leverage + lower risk% = same $ at risk
        but better R:R.
        """
        prev_risk = 1.0
        for conf in [3, 4, 5]:
            r_prec = self.sizer_prec.size(**self._params(conf))
            self.assertIsNotNone(r_prec)
            self.assertLessEqual(
                r_prec.risk_pct, prev_risk,
                f"Precision risk should decrease at conf={conf}"
            )
            prev_risk = r_prec.risk_pct


class TestConvictionSizerHighLevStreakBreaker(unittest.TestCase):
    """Test the high-leverage streak breaker."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sizer = ConvictionSizer(log_path=os.path.join(self.tmp, "test.jsonl"))

    def _params(self, confluences=5):
        return dict(
            equity=89.0,
            entry_price=HYPE_ENTRY,
            sl_price=HYPE_SL,
            tp_price=HYPE_TP,
            confluences=confluences,
            symbol="HYPE",
            side="BUY",
            utc_hour=12,
        )

    def test_two_high_lev_losses_force_base(self):
        """2 consecutive high-lev losses should force base leverage for 3 trades."""
        self.sizer.record_outcome(False, leverage_used=15.0)
        self.sizer.record_outcome(False, leverage_used=15.0)
        # Next trade should be forced to base leverage (<=5x)
        result = self.sizer.size(**self._params(confluences=5))
        self.assertIsNotNone(result)
        self.assertLessEqual(result.leverage, 5.0)
        any_forced = any("forced_base" in m for m in result.modifiers_applied)
        self.assertTrue(any_forced)


if __name__ == "__main__":
    unittest.main()
