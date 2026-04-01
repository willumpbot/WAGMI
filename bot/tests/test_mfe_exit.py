"""
Tests for MFE-aware exit intelligence module.
Covers all recommendation types: HOLD, TAKE_PROFIT, TIGHTEN_STOP, EXIT_NOW.
"""

import time
import pytest
from execution.mfe_exit import (
    MFEExitAdvisor,
    ExitRecommendation,
    MFE_MAE_DATA,
    DEFAULT_MFE_MAE,
    should_take_profit,
    get_exit_recommendation,
)


@pytest.fixture
def advisor():
    return MFEExitAdvisor()


def _ts_hours_ago(hours: float) -> float:
    """Return a Unix timestamp `hours` in the past."""
    return time.time() - hours * 3600


class TestTakeProfit:
    """Rule: uPnL > 2x median MFE -> TAKE_PROFIT."""

    def test_btc_short_above_2x_mfe(self, advisor):
        # BTC MFE p50 = 0.38%. A 0.80% move exceeds 2x.
        entry = 100_000.0
        price = 99_200.0  # 0.8% in our favor for SHORT
        rec = advisor.evaluate("BTC", "SELL", entry, price, _ts_hours_ago(1.0))
        assert rec.action == "TAKE_PROFIT"
        assert rec.urgency == "high"
        assert rec.mfe_ratio >= 2.0

    def test_sol_long_above_2x_mfe(self, advisor):
        # SOL MFE p50 = 0.51%. A 1.1% move exceeds 2x.
        entry = 150.0
        price = 151.65  # +1.1%
        rec = advisor.evaluate("SOL", "BUY", entry, price, _ts_hours_ago(0.5))
        assert rec.action == "TAKE_PROFIT"

    def test_hype_needs_larger_move_for_tp(self, advisor):
        # HYPE MFE p50 = 0.78%. A 1.0% move is only ~1.28x MFE — not enough.
        entry = 20.0
        price = 19.80  # 1.0% SHORT profit
        rec = advisor.evaluate("HYPE", "SELL", entry, price, _ts_hours_ago(1.0))
        assert rec.action != "TAKE_PROFIT"


class TestTightenStop:
    """Rule: uPnL > 1.5x median MFE + fading momentum -> TIGHTEN_STOP."""

    def test_tighten_when_volume_below_avg(self, advisor):
        # ETH MFE p50 = 0.44%. A 0.70% move = 1.59x. Volume fading.
        entry = 3000.0
        price = 2979.0  # 0.70% SHORT profit
        rec = advisor.evaluate(
            "ETH", "SELL", entry, price, _ts_hours_ago(1.0),
            current_volume=500, avg_volume=1000,  # volume fading
        )
        assert rec.action == "TIGHTEN_STOP"
        assert rec.urgency == "medium"

    def test_no_tighten_when_volume_strong(self, advisor):
        # Same uPnL but volume is strong — should HOLD (not enough for TP).
        entry = 3000.0
        price = 2979.0  # 0.70% SHORT profit = 1.59x MFE
        rec = advisor.evaluate(
            "ETH", "SELL", entry, price, _ts_hours_ago(1.0),
            current_volume=1200, avg_volume=1000,  # volume holding up
        )
        # Volume is above avg, so momentum not fading, but not a spike either
        assert rec.action == "HOLD"

    def test_tighten_with_no_volume_data(self, advisor):
        # No volume data — conservative assumption: momentum fading.
        entry = 3000.0
        price = 2979.0  # 0.70% SHORT profit
        rec = advisor.evaluate(
            "ETH", "SELL", entry, price, _ts_hours_ago(1.0),
        )
        assert rec.action == "TIGHTEN_STOP"


class TestExitNow:
    """Rules: loser timeout (4h) and deep drawdown (2h + >1x MAE)."""

    def test_loser_after_4h(self, advisor):
        # BTC SHORT, 4.5h open, small loss
        entry = 100_000.0
        price = 100_100.0  # -0.10% loss for SHORT
        rec = advisor.evaluate("BTC", "SELL", entry, price, _ts_hours_ago(4.5))
        assert rec.action == "EXIT_NOW"
        assert rec.hold_hours >= 4.0

    def test_deep_drawdown_after_2h(self, advisor):
        # SOL SHORT, 2.5h open, drawdown = 0.50% > MAE p50 (0.47%)
        entry = 150.0
        price = 150.75  # -0.50% for SHORT
        rec = advisor.evaluate("SOL", "SELL", entry, price, _ts_hours_ago(2.5))
        assert rec.action == "EXIT_NOW"
        assert rec.urgency == "critical"
        assert rec.mae_ratio >= 1.0

    def test_no_exit_if_loss_small_and_young(self, advisor):
        # SOL SHORT, 1h open, small loss — should HOLD
        entry = 150.0
        price = 150.30  # -0.20% loss
        rec = advisor.evaluate("SOL", "SELL", entry, price, _ts_hours_ago(1.0))
        assert rec.action == "HOLD"


class TestVolumeSpikeHold:
    """Rule: volume spike + positive uPnL -> HOLD (momentum cascade)."""

    def test_volume_spike_overrides_take_profit(self, advisor):
        # BTC SHORT, uPnL = 0.80% (>2x MFE) but volume spike → HOLD
        entry = 100_000.0
        price = 99_200.0
        rec = advisor.evaluate(
            "BTC", "SELL", entry, price, _ts_hours_ago(1.0),
            current_volume=5000, avg_volume=1000,  # 5x spike
        )
        assert rec.action == "HOLD"
        assert "spike" in rec.reason.lower()


class TestConvenienceFunctions:
    """Module-level convenience wrappers."""

    def test_should_take_profit_true(self):
        # BTC SHORT with large gain
        result = should_take_profit(
            symbol="BTC", entry=100_000, current_price=99_200,
            side="SELL", leverage=10, hold_hours=1.0,
        )
        assert result is True

    def test_should_take_profit_false(self):
        # BTC SHORT with tiny gain
        result = should_take_profit(
            symbol="BTC", entry=100_000, current_price=99_950,
            side="SELL", leverage=10, hold_hours=0.5,
        )
        assert result is False

    def test_get_exit_recommendation(self):
        rec = get_exit_recommendation(
            symbol="ETH", side="SELL", entry_price=3000.0,
            current_price=2990.0, open_timestamp=_ts_hours_ago(0.5),
        )
        assert isinstance(rec, ExitRecommendation)
        assert rec.action in ("HOLD", "TAKE_PROFIT", "TIGHTEN_STOP", "EXIT_NOW")


class TestSymbolNormalisation:
    """Ensure exchange-style symbols map correctly."""

    def test_btc_usdt_suffix(self, advisor):
        assert advisor._normalise_symbol("BTC/USDT:USDT") == "BTC"

    def test_sol_perp(self, advisor):
        assert advisor._normalise_symbol("SOL-PERP") == "SOL"

    def test_unknown_symbol_uses_default(self, advisor):
        entry = 1.0
        price = 0.99  # 1% SHORT profit
        rec = advisor.evaluate("DOGE", "SELL", entry, price, _ts_hours_ago(0.5))
        # Should still work using DEFAULT_MFE_MAE
        assert rec.action == "TAKE_PROFIT"  # 1% >> 2*0.40%


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_zero_hold_time(self, advisor):
        rec = advisor.evaluate("BTC", "SELL", 100_000, 100_000, time.time())
        assert rec.action == "HOLD"
        assert rec.upnl_pct == 0.0

    def test_breakeven_position(self, advisor):
        rec = advisor.evaluate("ETH", "BUY", 3000, 3000, _ts_hours_ago(1.0))
        assert rec.action == "HOLD"

    def test_long_position_profit(self, advisor):
        # Verify BUY side uPnL calculation
        entry = 150.0
        price = 152.0  # +1.33%
        rec = advisor.evaluate("SOL", "BUY", entry, price, _ts_hours_ago(0.5))
        assert rec.upnl_pct > 1.0
        assert rec.action == "TAKE_PROFIT"  # 1.33% >> 2*0.51%
