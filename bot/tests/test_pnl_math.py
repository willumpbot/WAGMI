"""
PnL math verification tests.

Ensures:
1. LONG PnL = (exit - entry) * qty * leverage
2. SHORT PnL = (entry - exit) * qty * leverage
3. Partial close at TP1 computes correctly
4. Fees are tracked separately and don't double-count
5. qty calculation matches risk_per_trade formula
6. No impossible PnL values
7. Price scale consistency
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager
from execution.risk import RiskManager


class TestPnLMathLong(unittest.TestCase):
    """Verify PnL computation for LONG positions."""

    def test_long_win_pnl(self):
        """LONG: exit > entry -> positive PnL."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "LONG", 50000.0, 1.0, 49000.0, 51000.0, 52000.0,
                               leverage=2.0, atr=500.0)
        events = pm.update_price("BTC", 51000.0)  # TP1
        events = pm.update_price("BTC", 52000.0)  # TP2 / trailing

        pos = pm.positions["BTC"]
        # Total PnL should be positive
        self.assertGreater(pos.realized_pnl, 0,
                           f"LONG winning trade should have positive PnL, got {pos.realized_pnl}")

    def test_long_loss_pnl(self):
        """LONG: exit < entry -> negative PnL."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "LONG", 50000.0, 1.0, 49000.0, 51000.0, 52000.0,
                               leverage=2.0, atr=500.0)
        events = pm.update_price("BTC", 49000.0)  # SL

        pos = pm.positions["BTC"]
        self.assertLess(pos.realized_pnl, 0,
                        f"LONG SL trade should have negative PnL, got {pos.realized_pnl}")

    def test_long_pnl_formula(self):
        """Verify exact formula: PnL = (exit - entry) * qty * leverage."""
        pm = PositionManager(taker_fee_bps=0)
        entry = 100.0
        qty = 10.0
        leverage = 5.0
        sl = 95.0
        pos = pm.open_position("TEST", "LONG", entry, qty, sl, 110.0, 120.0,
                               leverage=leverage, atr=3.0)
        # Force close at 110
        event = pm.force_close("TEST", 110.0, "TEST")
        expected_pnl = (110.0 - 100.0) * qty * leverage  # = 500
        self.assertAlmostEqual(event.pnl, expected_pnl, places=2,
                               msg=f"LONG PnL should be {expected_pnl}, got {event.pnl}")


class TestPnLMathShort(unittest.TestCase):
    """Verify PnL computation for SHORT positions."""

    def test_short_win_pnl(self):
        """SHORT: exit < entry -> positive PnL."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "SHORT", 50000.0, 1.0, 51000.0, 49000.0, 48000.0,
                               leverage=2.0, atr=500.0)
        event = pm.force_close("BTC", 49000.0, "TEST")
        expected = (50000.0 - 49000.0) * 1.0 * 2.0  # = 2000
        self.assertAlmostEqual(event.pnl, expected, places=2)

    def test_short_loss_pnl(self):
        """SHORT: exit > entry -> negative PnL."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("BTC", "SHORT", 50000.0, 1.0, 51000.0, 49000.0, 48000.0,
                               leverage=2.0, atr=500.0)
        events = pm.update_price("BTC", 51000.0)  # SL

        pos = pm.positions["BTC"]
        self.assertLess(pos.realized_pnl, 0)

    def test_short_pnl_formula(self):
        """Verify exact formula: PnL = (entry - exit) * qty * leverage."""
        pm = PositionManager(taker_fee_bps=0)
        entry = 100.0
        qty = 10.0
        leverage = 5.0
        pos = pm.open_position("TEST", "SHORT", entry, qty, 105.0, 90.0, 80.0,
                               leverage=leverage, atr=3.0)
        event = pm.force_close("TEST", 90.0, "TEST")
        expected_pnl = (100.0 - 90.0) * qty * leverage  # = 500
        self.assertAlmostEqual(event.pnl, expected_pnl, places=2)


class TestPartialCloseTP1(unittest.TestCase):
    """Verify TP1 partial close PnL math."""

    def test_tp1_partial_pnl_correct(self):
        """TP1 partial close should compute PnL on the closed portion only."""
        pm = PositionManager(taker_fee_bps=0, enable_trailing=True, trailing_atr_mult=1.5)
        entry = 100.0
        qty = 10.0
        leverage = 2.0
        tp1 = 105.0
        # Default tp1_close_pct depends on profile, but without profile it's ~0.60
        pos = pm.open_position("TEST", "LONG", entry, qty, 95.0, tp1, 110.0,
                               leverage=leverage, atr=3.0, tp1_close_pct=0.60)

        events = pm.update_price("TEST", tp1)
        self.assertTrue(len(events) > 0)

        tp1_event = events[0]
        close_qty = qty * 0.60  # 6.0 units closed
        expected_pnl = (tp1 - entry) * close_qty * leverage
        self.assertAlmostEqual(tp1_event.pnl, expected_pnl, places=1,
                               msg=f"TP1 PnL should be {expected_pnl}, got {tp1_event.pnl}")

    def test_tp1_remaining_qty(self):
        """After TP1, remaining qty should be (1 - tp1_close_pct) * original."""
        pm = PositionManager(taker_fee_bps=0, enable_trailing=True, trailing_atr_mult=1.5)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 105.0, 110.0,
                               leverage=2.0, atr=3.0, tp1_close_pct=0.60)
        pm.update_price("TEST", 105.0)  # TP1
        pos = pm.positions["TEST"]
        expected_remaining = 10.0 * (1 - 0.60)  # 4.0
        self.assertAlmostEqual(pos.qty, expected_remaining, places=1)


class TestFeeAccounting(unittest.TestCase):
    """Verify fees are tracked correctly and don't double-count."""

    def test_fees_deducted_from_realized_pnl(self):
        """pos.realized_pnl should be net of fees."""
        pm = PositionManager(taker_fee_bps=10)  # 0.1% fee
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 110.0, 120.0,
                               leverage=2.0, atr=3.0)
        event = pm.force_close("TEST", 110.0, "TEST")

        pos = pm.positions["TEST"]
        gross_pnl = (110.0 - 100.0) * 10.0 * 2.0  # = 200
        self.assertLess(pos.realized_pnl, gross_pnl,
                        "Net PnL should be less than gross due to fees")
        self.assertGreater(pos.fees_paid, 0, "Fees should be positive")

    def test_event_pnl_is_gross(self):
        """TradeEvent.pnl should be gross (before fees)."""
        pm = PositionManager(taker_fee_bps=10)
        pos = pm.open_position("TEST", "LONG", 100.0, 10.0, 95.0, 110.0, 120.0,
                               leverage=2.0, atr=3.0)
        event = pm.force_close("TEST", 110.0, "TEST")
        expected_gross = (110.0 - 100.0) * 10.0 * 2.0
        self.assertAlmostEqual(event.pnl, expected_gross, places=2,
                               msg="TradeEvent.pnl should be gross PnL")


class TestQtyRiskConsistency(unittest.TestCase):
    """Verify qty calculation matches risk_per_trade formula."""

    def test_qty_formula(self):
        """qty = risk_amount / (effective_stop * leverage), where effective_stop includes fees."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        entry = 100.0
        sl = 95.0  # stop_distance = 5
        leverage = 2.0
        qty = rm.calculate_qty(entry, sl, leverage=leverage)

        # risk_amount = 10000 * 0.01 = 100
        # effective_stop = 5.0 + 0.08 (round-trip fees at 4bps*2) = 5.08
        # qty = 100 / (5.08 * 2) ≈ 9.84
        self.assertAlmostEqual(qty, 9.84, places=1)

        # Verify effective dollar risk: effective_stop * qty * leverage ≈ risk_amount
        from trading_config import TradingConfig
        fee_bps = TradingConfig().taker_fee_bps
        fee_width = entry * (fee_bps * 2 / 10000.0)
        effective_stop = abs(entry - sl) + fee_width
        dollar_risk = effective_stop * qty * leverage
        expected_risk = 10000 * 0.01
        self.assertAlmostEqual(dollar_risk, expected_risk, places=1,
                               msg=f"Dollar risk should be ${expected_risk}, got ${dollar_risk}")

    def test_max_loss_equals_risk_amount(self):
        """If SL hits exactly, loss should equal risk_amount."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.01)
        pm = PositionManager(taker_fee_bps=0)

        entry = 100.0
        sl = 95.0
        leverage = 3.0
        qty = rm.calculate_qty(entry, sl, leverage=leverage)

        pos = pm.open_position("TEST", "LONG", entry, qty, sl, 110.0, 120.0,
                               leverage=leverage, atr=3.0)
        events = pm.update_price("TEST", sl)

        loss = abs(events[0].pnl)
        expected_risk = 10000 * 0.01  # $100
        # Loss should be approximately equal to risk_amount
        self.assertAlmostEqual(loss, expected_risk, delta=expected_risk * 0.05,
                               msg=f"SL loss ${loss:.2f} should equal risk ${expected_risk:.2f}")


class TestNoPriceScaleBugs(unittest.TestCase):
    """Detect price scale bugs (e.g., 0.0042 vs 0.0000042)."""

    def test_btc_price_scale(self):
        """BTC prices should be in the $20k-$200k range."""
        pm = PositionManager(taker_fee_bps=0)
        entry = 95000.0
        pos = pm.open_position("BTC", "LONG", entry, 0.01, 94000.0, 96000.0, 97000.0,
                               leverage=2.0, atr=500.0)
        event = pm.force_close("BTC", 96000.0, "TEST")
        # PnL should be reasonable: (96000-95000) * 0.01 * 2 = 20
        self.assertAlmostEqual(event.pnl, 20.0, places=1)

    def test_sol_price_scale(self):
        """SOL prices should be in the $10-$500 range."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("SOL", "SHORT", 150.0, 1.0, 155.0, 145.0, 140.0,
                               leverage=3.0, atr=5.0)
        event = pm.force_close("SOL", 145.0, "TEST")
        # PnL = (150-145) * 1 * 3 = 15
        self.assertAlmostEqual(event.pnl, 15.0, places=1)

    def test_micro_price_hype(self):
        """HYPE at small prices should still compute correctly."""
        pm = PositionManager(taker_fee_bps=0)
        pos = pm.open_position("HYPE", "LONG", 25.5, 10.0, 24.5, 26.5, 27.5,
                               leverage=5.0, atr=0.5)
        event = pm.force_close("HYPE", 26.5, "TEST")
        # PnL = (26.5-25.5) * 10 * 5 = 50
        self.assertAlmostEqual(event.pnl, 50.0, places=1)


if __name__ == "__main__":
    unittest.main()
