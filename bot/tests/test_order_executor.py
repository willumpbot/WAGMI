"""
Tests for OrderExecutor — the bridge between PositionManager and exchange.

Tests cover:
  - Paper mode fills (simulated)
  - Input validation (bad symbols, zero qty, min qty)
  - Slippage protection
  - Order result parsing
  - Leverage setting
  - Stats tracking
  - Live mode with mocked exchange
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.order_executor import OrderExecutor, OrderResult, SYMBOL_TO_PAIR, create_executor


# ── OrderResult Tests ────────────────────────────────────────────────


class TestOrderResult:
    def test_default_not_filled(self):
        r = OrderResult()
        assert not r.filled
        assert not r.success

    def test_filled_property(self):
        r = OrderResult(success=True, status="filled")
        assert r.filled

    def test_partially_filled(self):
        r = OrderResult(success=True, status="partially_filled")
        assert r.filled

    def test_error_not_filled(self):
        r = OrderResult(success=False, status="error", error="network timeout")
        assert not r.filled


# ── Paper Mode Tests ─────────────────────────────────────────────────


class TestPaperMode:
    def setup_method(self):
        self.executor = OrderExecutor(exchange=None, mode="paper")

    def test_open_position_paper(self):
        result = self.executor.open_position("BTC", "BUY", qty=0.001, price=50000.0, leverage=5)
        assert result.filled
        assert result.mode == "paper"
        assert result.fill_qty == 0.001
        assert result.fill_price > 0
        assert result.fees > 0
        assert "paper_" in result.order_id

    def test_close_position_paper(self):
        result = self.executor.close_position("SOL", "SELL", qty=1.0, price=150.0, reason="TP1_HIT")
        assert result.filled
        assert result.fill_qty == 1.0

    def test_paper_slippage_buy(self):
        result = self.executor.open_position("BTC", "BUY", qty=0.001, price=50000.0)
        # Buy should fill slightly above expected price
        assert result.fill_price >= 50000.0

    def test_paper_slippage_sell(self):
        result = self.executor.open_position("ETH", "SELL", qty=0.01, price=3000.0)
        # Sell should fill slightly below expected price
        assert result.fill_price <= 3000.0

    def test_paper_fees(self):
        result = self.executor.open_position("SOL", "BUY", qty=10.0, price=150.0)
        # Notional ~= 10 * 150 = 1500, fees ~= 1500 * 0.00025 = 0.375
        assert 0.3 < result.fees < 0.5

    def test_set_leverage_paper(self):
        assert self.executor.set_leverage("BTC", 10) is True

    def test_get_balance_paper(self):
        assert self.executor.get_balance() is None


# ── Validation Tests ─────────────────────────────────────────────────


class TestValidation:
    def setup_method(self):
        self.executor = OrderExecutor(exchange=None, mode="paper")

    def test_unknown_symbol_rejected(self):
        result = self.executor.open_position("FAKECOIN", "BUY", qty=1.0, price=1.0)
        assert not result.filled
        assert "Unknown symbol" in result.error

    def test_zero_qty_rejected(self):
        # round_qty rounds down, so 0.0001 for BTC (min_qty=0.001) rounds to 0.00010
        result = self.executor.open_position("BTC", "BUY", qty=0.0001, price=50000.0)
        assert not result.filled
        assert "below minimum" in result.error

    def test_zero_price_rejected(self):
        result = self.executor.open_position("BTC", "BUY", qty=0.001, price=0.0)
        assert not result.filled
        assert "Invalid price" in result.error

    def test_close_unknown_symbol(self):
        result = self.executor.close_position("FAKE", "SELL", qty=1.0, price=100.0)
        assert not result.filled

    def test_close_zero_qty(self):
        result = self.executor.close_position("BTC", "SELL", qty=0.0, price=50000.0)
        assert not result.filled


# ── Stats Tests ──────────────────────────────────────────────────────


class TestStats:
    def test_stats_tracking(self):
        executor = OrderExecutor(exchange=None, mode="paper")
        executor.open_position("BTC", "BUY", qty=0.001, price=50000.0)
        executor.open_position("SOL", "SELL", qty=1.0, price=150.0)

        stats = executor.get_stats()
        assert stats["orders_submitted"] == 2
        assert stats["orders_filled"] == 2
        assert stats["orders_failed"] == 0
        assert stats["fill_rate"] == 1.0
        assert stats["total_fees"] > 0
        assert stats["mode"] == "paper"

    def test_stats_include_failed(self):
        executor = OrderExecutor(exchange=None, mode="paper")
        executor.open_position("FAKE", "BUY", qty=1.0, price=1.0)  # Fails validation
        stats = executor.get_stats()
        assert stats["orders_submitted"] == 0  # Validation fails before submit


# ── Live Mode Tests (Mocked Exchange) ────────────────────────────────


class TestLiveMode:
    def _mock_exchange(self):
        ex = MagicMock()
        ex.create_market_order.return_value = {
            "id": "order_123",
            "status": "closed",
            "filled": 0.001,
            "average": 50005.0,
            "amount": 0.001,
            "cost": 50.005,
            "fee": {"cost": 0.0125, "currency": "USDC"},
        }
        ex.create_limit_order.return_value = {
            "id": "order_456",
            "status": "closed",
            "filled": 0.001,
            "average": 50000.0,
            "amount": 0.001,
            "cost": 50.0,
            "fee": {"cost": 0.0125, "currency": "USDC"},
        }
        ex.set_leverage.return_value = {}
        ex.fetch_balance.return_value = {"USDC": {"free": 1000.0, "total": 1200.0}}
        ex.fetch_ticker.return_value = {"last": 50000.0}  # Realistic BTC price for sanity checks
        return ex

    def test_live_mode_requires_exchange(self):
        with pytest.raises(ValueError, match="requires a CCXT exchange"):
            OrderExecutor(exchange=None, mode="live")

    def test_live_market_order(self):
        ex = self._mock_exchange()
        executor = OrderExecutor(exchange=ex, mode="live")
        result = executor.open_position("BTC", "BUY", qty=0.001, price=50000.0, leverage=5)

        assert result.filled
        assert result.order_id == "order_123"
        assert result.fill_price == 50005.0
        assert result.fill_qty == 0.001
        assert result.mode == "live"
        ex.set_leverage.assert_called_once()
        ex.create_market_order.assert_called_once()

    def test_live_limit_order(self):
        ex = self._mock_exchange()
        executor = OrderExecutor(exchange=ex, mode="live")
        result = executor.open_position(
            "BTC", "BUY", qty=0.001, price=50000.0, leverage=5, order_type="limit"
        )
        assert result.filled
        ex.create_limit_order.assert_called_once()

    def test_live_close_reduce_only(self):
        ex = self._mock_exchange()
        executor = OrderExecutor(exchange=ex, mode="live")
        result = executor.close_position("BTC", "SELL", qty=0.001, price=50000.0, reason="SL_HIT")

        assert result.filled
        call_args = ex.create_market_order.call_args
        assert call_args[1]["params"]["reduceOnly"] is True

    def test_live_retry_on_failure(self):
        ex = self._mock_exchange()
        ex.create_market_order.side_effect = [
            Exception("network timeout"),
            {
                "id": "order_789",
                "status": "closed",
                "filled": 0.001,
                "average": 50000.0,
                "amount": 0.001,
                "cost": 50.0,
                "fee": {"cost": 0.0125},
            },
        ]
        executor = OrderExecutor(exchange=ex, mode="live", max_retries=2)
        result = executor.open_position("BTC", "BUY", qty=0.001, price=50000.0, leverage=5)

        assert result.filled
        assert ex.create_market_order.call_count == 2

    def test_live_all_retries_fail(self):
        ex = self._mock_exchange()
        ex.create_market_order.side_effect = Exception("exchange down")
        executor = OrderExecutor(exchange=ex, mode="live", max_retries=2)

        with patch("time.sleep"):  # Don't actually wait
            result = executor.open_position("BTC", "BUY", qty=0.001, price=50000.0, leverage=5)

        assert not result.filled
        assert "failed after" in result.error.lower()
        stats = executor.get_stats()
        assert stats["orders_failed"] == 1

    def test_live_get_balance(self):
        ex = self._mock_exchange()
        executor = OrderExecutor(exchange=ex, mode="live")
        balance = executor.get_balance()
        assert balance == 1000.0

    def test_live_set_leverage_retry(self):
        ex = self._mock_exchange()
        ex.set_leverage.side_effect = [Exception("timeout"), None]
        executor = OrderExecutor(exchange=ex, mode="live", max_retries=2)

        with patch("time.sleep"):
            assert executor.set_leverage("BTC", 10) is True
        assert ex.set_leverage.call_count == 2


# ── Slippage Tests ───────────────────────────────────────────────────


class TestSlippage:
    def test_high_slippage_warning(self):
        ex = MagicMock()
        ex.create_market_order.return_value = {
            "id": "order_slip",
            "status": "closed",
            "filled": 0.001,
            "average": 51000.0,  # 2% slippage on $50k
            "amount": 0.001,
            "cost": 51.0,
            "fee": {"cost": 0.0},
        }
        ex.set_leverage.return_value = {}
        ex.fetch_ticker.return_value = {"last": 50000.0}

        executor = OrderExecutor(exchange=ex, mode="live", max_slippage_pct=1.5)
        result = executor.open_position("BTC", "BUY", qty=0.001, price=50000.0, leverage=1)
        # Should still fill but log a warning
        assert result.filled
        assert result.fill_price == 51000.0


# ── Factory Tests ────────────────────────────────────────────────────


class TestFactory:
    def test_create_executor_paper(self):
        executor = create_executor(fetcher=None, mode="paper")
        assert executor.mode == "paper"
        assert executor.exchange is None

    def test_create_executor_with_fetcher(self):
        fetcher = MagicMock()
        fetcher._exchanges = {"hyperliquid": MagicMock()}
        executor = create_executor(fetcher=fetcher, mode="paper")
        assert executor.exchange is not None

    def test_create_executor_live_no_exchange_raises(self):
        fetcher = MagicMock()
        fetcher._exchanges = {}
        # Live mode without exchange should raise
        with pytest.raises(ValueError, match="requires a CCXT exchange"):
            create_executor(fetcher=fetcher, mode="live")


# ── Symbol Mapping Tests ─────────────────────────────────────────────


class TestSymbolMapping:
    def test_all_default_symbols_mapped(self):
        from trading_config import DEFAULT_SYMBOLS
        for symbol in DEFAULT_SYMBOLS:
            assert symbol in SYMBOL_TO_PAIR, f"{symbol} missing from SYMBOL_TO_PAIR"

    def test_pepe_uses_kpepe(self):
        assert SYMBOL_TO_PAIR["PEPE"] == "KPEPE/USDC:USDC"

    def test_btc_pair_format(self):
        assert SYMBOL_TO_PAIR["BTC"] == "BTC/USDC:USDC"
