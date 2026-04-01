"""
Tests for pre-order sanity checks in OrderExecutor.

Validates the 5-gate validation layer that catches:
1. Below-minimum notional orders
2. Oversized positions (% of equity)
3. Excessive leverage
4. Duplicate positions (same symbol + direction)
5. Stale prices (entry far from market)
"""

import pytest
from unittest.mock import MagicMock, patch
from execution.order_executor import OrderExecutor, OrderResult, MIN_NOTIONAL_USD, MAX_POSITION_EQUITY_PCT, MAX_PRICE_DEVIATION_PCT


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def executor():
    """Basic paper-mode executor with equity context set."""
    ex = OrderExecutor(mode="paper")
    ex.set_sanity_context(account_equity=1000.0, max_leverage=15.0)
    return ex


@pytest.fixture
def executor_with_positions():
    """Executor with a mock position manager that has an open BTC LONG."""
    ex = OrderExecutor(mode="paper")
    mock_pm = MagicMock()
    mock_pos = MagicMock()
    mock_pos.side = "BUY"
    mock_pm.get_open_positions.return_value = {"BTC": mock_pos}
    ex.set_sanity_context(
        position_manager=mock_pm,
        account_equity=100000.0,  # Large equity so BTC orders pass size check
        max_leverage=15.0,
    )
    return ex


# ── 1. Minimum Notional ────────────────────────────────────────


class TestMinNotional:
    def test_reject_below_minimum(self, executor):
        """Orders with notional < $10 are rejected."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.01, price=100.0)
        # notional = 0.01 * 100 = $1
        assert not ok
        assert "BELOW_MIN_NOTIONAL" in reason

    def test_accept_at_minimum(self, executor):
        """Orders exactly at $10 notional pass."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.1, price=100.0)
        # notional = 0.1 * 100 = $10
        assert ok
        assert reason == "OK"

    def test_accept_above_minimum(self, executor):
        """Normal-sized orders pass."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=1.0, price=100.0)
        assert ok

    def test_tiny_btc_order_rejected(self, executor):
        """Very small BTC order is caught."""
        ok, reason = executor.validate_order("BTC", "BUY", qty=0.0001, price=80000.0)
        # notional = 0.0001 * 80000 = $8
        assert not ok
        assert "BELOW_MIN_NOTIONAL" in reason


# ── 2. Maximum Position Size ───────────────────────────────────


class TestMaxPositionSize:
    def test_reject_oversized(self, executor):
        """Position > 20% of equity is rejected."""
        # equity=1000, 20% = $200. Order is $300
        ok, reason = executor.validate_order("SOL", "BUY", qty=3.0, price=100.0)
        assert not ok
        assert "EXCEEDS_MAX_SIZE" in reason

    def test_accept_within_limit(self, executor):
        """Position <= 20% of equity passes."""
        # equity=1000, 20% = $200. Order is $150
        ok, reason = executor.validate_order("SOL", "BUY", qty=1.5, price=100.0)
        assert ok

    def test_skip_if_no_equity(self):
        """Check is skipped when equity is not set (0)."""
        ex = OrderExecutor(mode="paper")
        # No equity set, so max size check is skipped
        ok, reason = ex.validate_order("SOL", "BUY", qty=100.0, price=100.0)
        # $10,000 notional but no equity reference -- passes
        assert ok

    def test_exact_boundary(self, executor):
        """Exactly 20% of equity passes."""
        # equity=1000, 20% = $200. Order is exactly $200
        ok, reason = executor.validate_order("SOL", "BUY", qty=2.0, price=100.0)
        assert ok

    def test_barely_over_boundary(self, executor):
        """Just over 20% is rejected."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=2.01, price=100.0)
        assert not ok
        assert "EXCEEDS_MAX_SIZE" in reason


# ── 3. Leverage Bounds ──────────────────────────────────────────


class TestLeverageBounds:
    def test_reject_high_leverage(self, executor):
        """Leverage above max (15x) is rejected."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=20)
        assert not ok
        assert "LEVERAGE_TOO_HIGH" in reason

    def test_accept_at_max_leverage(self, executor):
        """Leverage exactly at max passes."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=15)
        assert ok

    def test_accept_low_leverage(self, executor):
        """Normal leverage passes."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=3)
        assert ok

    def test_default_leverage_cap(self):
        """Default max leverage is 25x when not configured."""
        ex = OrderExecutor(mode="paper")
        ok, _ = ex.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=25)
        assert ok
        ok, reason = ex.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=26)
        assert not ok
        assert "LEVERAGE_TOO_HIGH" in reason


# ── 4. Duplicate Position ──────────────────────────────────────


class TestDuplicatePosition:
    def test_reject_same_direction(self, executor_with_positions):
        """Duplicate BTC BUY is rejected when BTC LONG already open."""
        ok, reason = executor_with_positions.validate_order(
            "BTC", "BUY", qty=0.01, price=80000.0, leverage=3
        )
        assert not ok
        assert "DUPLICATE_POSITION" in reason

    def test_allow_opposite_direction(self, executor_with_positions):
        """BTC SELL (flip) is allowed when BTC LONG is open."""
        ok, reason = executor_with_positions.validate_order(
            "BTC", "SELL", qty=0.01, price=80000.0, leverage=3
        )
        assert ok

    def test_allow_different_symbol(self, executor_with_positions):
        """SOL BUY is allowed when only BTC is open."""
        ok, reason = executor_with_positions.validate_order(
            "SOL", "BUY", qty=1.0, price=100.0, leverage=3
        )
        assert ok

    def test_skip_if_no_position_manager(self):
        """Check is skipped when no position manager is set."""
        ex = OrderExecutor(mode="paper")
        ex.set_sanity_context(account_equity=100000.0, max_leverage=15.0)
        ok, reason = ex.validate_order("BTC", "BUY", qty=0.01, price=80000.0, leverage=3)
        # No position manager, so duplicate check is skipped
        assert ok


# ── 5. Price Sanity ─────────────────────────────────────────────


class TestPriceSanity:
    def test_reject_stale_price_high(self, executor):
        """Entry 10% above market is rejected."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=110.0, leverage=1,
            current_market_price=100.0,
        )
        assert not ok
        assert "STALE_PRICE" in reason

    def test_reject_stale_price_low(self, executor):
        """Entry 10% below market is rejected."""
        ok, reason = executor.validate_order(
            "SOL", "SELL", qty=1.0, price=90.0, leverage=1,
            current_market_price=100.0,
        )
        assert not ok
        assert "STALE_PRICE" in reason

    def test_accept_close_to_market(self, executor):
        """Entry within 5% of market passes."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=103.0, leverage=1,
            current_market_price=100.0,
        )
        assert ok

    def test_skip_if_no_market_price(self, executor):
        """Check is skipped when current_market_price is None."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=200.0, leverage=1,
            current_market_price=None,
        )
        assert ok

    def test_exactly_at_boundary(self, executor):
        """Entry exactly 5% away passes (boundary inclusive)."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=105.0, leverage=1,
            current_market_price=100.0,
        )
        assert ok

    def test_just_over_boundary(self, executor):
        """Entry 5.1% away is rejected."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=105.1, leverage=1,
            current_market_price=100.0,
        )
        assert not ok
        assert "STALE_PRICE" in reason


# ── Rejection Counters ──────────────────────────────────────────


class TestRejectionStats:
    def test_counters_increment(self, executor):
        """Each rejection increments the correct counter."""
        executor.validate_order("SOL", "BUY", qty=0.01, price=100.0)  # below min
        executor.validate_order("SOL", "BUY", qty=0.01, price=100.0)  # below min again
        stats = executor.get_rejection_stats()
        assert stats.get("below_min_notional", 0) == 2

    def test_multiple_categories(self, executor):
        """Different rejection types tracked separately."""
        executor.validate_order("SOL", "BUY", qty=0.01, price=100.0)  # below min
        executor.validate_order("SOL", "BUY", qty=0.5, price=100.0, leverage=20)  # leverage
        stats = executor.get_rejection_stats()
        assert stats.get("below_min_notional", 0) == 1
        assert stats.get("leverage_too_high", 0) == 1

    def test_stats_in_get_stats(self, executor):
        """Rejection stats are included in get_stats() output."""
        executor.validate_order("SOL", "BUY", qty=0.01, price=100.0)
        stats = executor.get_stats()
        assert "sanity_rejections" in stats
        assert stats["sanity_rejections"].get("below_min_notional", 0) == 1


# ── Integration: open_position calls validate_order ─────────────


class TestOpenPositionIntegration:
    def test_open_position_rejects_tiny_order(self):
        """open_position returns error for sub-minimum orders."""
        ex = OrderExecutor(mode="paper")
        ex.set_sanity_context(account_equity=1000.0, max_leverage=15.0)
        result = ex.open_position("SOL", "BUY", qty=0.001, price=100.0, leverage=2)
        # qty=0.001 is below min_qty for SOL, caught by existing check or sanity
        # Either way, should not be a successful fill
        assert not result.filled

    def test_open_position_rejects_high_leverage(self):
        """open_position returns error for excessive leverage."""
        ex = OrderExecutor(mode="paper")
        ex.set_sanity_context(account_equity=10000.0, max_leverage=15.0)
        result = ex.open_position("SOL", "BUY", qty=1.0, price=100.0, leverage=20)
        assert not result.filled
        assert "Sanity check failed" in result.error
        assert "LEVERAGE_TOO_HIGH" in result.error

    def test_open_position_passes_valid_order(self):
        """Valid orders pass sanity and get paper-filled."""
        ex = OrderExecutor(mode="paper")
        ex.set_sanity_context(account_equity=10000.0, max_leverage=15.0)
        result = ex.open_position("SOL", "BUY", qty=1.0, price=100.0, leverage=5)
        assert result.filled

    def test_open_position_rejects_duplicate(self):
        """Duplicate same-direction position is rejected at order level."""
        ex = OrderExecutor(mode="paper")
        mock_pm = MagicMock()
        mock_pos = MagicMock()
        mock_pos.side = "BUY"
        mock_pm.get_open_positions.return_value = {"SOL": mock_pos}
        ex.set_sanity_context(
            position_manager=mock_pm,
            account_equity=10000.0,
            max_leverage=15.0,
        )
        result = ex.open_position("SOL", "BUY", qty=1.0, price=100.0, leverage=5)
        assert not result.filled
        assert "DUPLICATE_POSITION" in result.error


# ── set_sanity_context ──────────────────────────────────────────


class TestSetSanityContext:
    def test_set_all(self):
        """All three context values are stored."""
        ex = OrderExecutor(mode="paper")
        mock_pm = MagicMock()
        ex.set_sanity_context(position_manager=mock_pm, account_equity=5000.0, max_leverage=10.0)
        assert ex._position_manager is mock_pm
        assert ex._account_equity == 5000.0
        assert ex._max_leverage == 10.0

    def test_partial_update(self):
        """Can update equity without resetting position_manager."""
        ex = OrderExecutor(mode="paper")
        mock_pm = MagicMock()
        ex.set_sanity_context(position_manager=mock_pm, account_equity=1000.0)
        ex.set_sanity_context(account_equity=2000.0)
        assert ex._position_manager is mock_pm  # unchanged
        assert ex._account_equity == 2000.0

    def test_defaults(self):
        """Default values when nothing is set."""
        ex = OrderExecutor(mode="paper")
        assert ex._position_manager is None
        assert ex._account_equity == 0.0
        assert ex._max_leverage == 25.0


# ── Edge Cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_price(self, executor):
        """Zero price creates zero notional, rejected by min check."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=1.0, price=0.0)
        assert not ok
        assert "BELOW_MIN_NOTIONAL" in reason

    def test_zero_qty(self, executor):
        """Zero qty creates zero notional, rejected by min check."""
        ok, reason = executor.validate_order("SOL", "BUY", qty=0.0, price=100.0)
        assert not ok
        assert "BELOW_MIN_NOTIONAL" in reason

    def test_all_checks_pass(self, executor):
        """A perfectly valid order passes all gates."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=1.0, price=100.0, leverage=5,
            current_market_price=100.0,
        )
        assert ok
        assert reason == "OK"

    def test_first_failing_check_wins(self, executor):
        """If multiple checks would fail, the first one (min notional) wins."""
        ok, reason = executor.validate_order(
            "SOL", "BUY", qty=0.01, price=100.0, leverage=20,
            current_market_price=200.0,
        )
        # notional=$1 fails min check before leverage check
        assert not ok
        assert "BELOW_MIN_NOTIONAL" in reason
