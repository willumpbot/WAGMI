"""
Tests for Push 1: Profitability Shield — new risk gates and cost awareness.

Tests:
- Portfolio notional cap (aggregate leverage limit)
- Spread-aware position sizing
- Funding cost tracking in PnL
- Backtest slippage model
- SL breakeven fee buffer fix (round-trip fees)
- Min profit threshold gate
- Config profile wiring (apply_profile)
- Per-symbol parameter overrides (get_symbol_param)
"""
import os
import sys
import math

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Portfolio Notional Cap
# ---------------------------------------------------------------------------

class TestPortfolioNotionalCap:
    """Test aggregate portfolio notional cap enforcement."""

    def test_get_total_open_notional_empty(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        assert pm.get_total_open_notional() == 0.0

    def test_get_total_open_notional_with_positions(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        pm.open_position("BTC", "LONG", 50000.0, 0.1, 49000.0, 52000.0, 55000.0, leverage=5.0)
        # notional = 0.1 * 50000 * 5 = 25000
        assert pm.get_total_open_notional() == pytest.approx(25000.0, rel=0.01)

    def test_check_portfolio_notional_cap_allows(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        # equity=10000, max_portfolio_leverage=3.0 => cap=30000
        allowed = pm.check_portfolio_notional_cap(
            new_notional=20000.0, equity=10000.0, max_portfolio_leverage=3.0,
        )
        assert allowed is True

    def test_check_portfolio_notional_cap_rejects(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        pm.open_position("BTC", "LONG", 50000.0, 0.1, 49000.0, 52000.0, 55000.0, leverage=5.0)
        # Current notional = 25000, cap=30000, new=10000 => 35000 > 30000
        allowed = pm.check_portfolio_notional_cap(
            new_notional=10000.0, equity=10000.0, max_portfolio_leverage=3.0,
        )
        assert allowed is False

    def test_check_portfolio_notional_cap_respects_custom_leverage(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        # Higher cap: equity=10000 * 5.0 = 50000
        allowed = pm.check_portfolio_notional_cap(
            new_notional=45000.0, equity=10000.0, max_portfolio_leverage=5.0,
        )
        assert allowed is True


# ---------------------------------------------------------------------------
# Spread-Aware Position Sizing
# ---------------------------------------------------------------------------

class TestSpreadAwareSizing:
    """Test that slippage/spread is added to stop distance for sizing."""

    def test_calculate_qty_without_slippage(self):
        from execution.risk import RiskManager, CircuitBreaker
        rm = RiskManager(
            starting_equity=10000.0,
            risk_per_trade=0.01,  # 1% = $100
            circuit_breaker=CircuitBreaker(),
        )
        qty = rm.calculate_qty(entry=100.0, stop_loss=99.0, leverage=1.0, slippage_bps=0)
        # risk=$100, stop=1.0 => qty=100
        assert qty == pytest.approx(100.0, rel=0.01)

    def test_calculate_qty_with_slippage_reduces_size(self):
        from execution.risk import RiskManager, CircuitBreaker
        rm = RiskManager(
            starting_equity=10000.0,
            risk_per_trade=0.01,
            circuit_breaker=CircuitBreaker(),
        )
        qty_no_slip = rm.calculate_qty(entry=100.0, stop_loss=99.0, leverage=1.0, slippage_bps=0)
        qty_with_slip = rm.calculate_qty(entry=100.0, stop_loss=99.0, leverage=1.0, slippage_bps=50)
        # With 50 bps slippage on $100 = $0.50 added to stop distance
        # effective_stop = 1.0 + 0.50 = 1.50
        # qty = 100 / 1.50 = 66.67
        assert qty_with_slip < qty_no_slip
        assert qty_with_slip == pytest.approx(100.0 / 1.5, rel=0.01)

    def test_calculate_qty_slippage_bps_zero_is_backward_compatible(self):
        from execution.risk import RiskManager, CircuitBreaker
        rm = RiskManager(
            starting_equity=10000.0,
            risk_per_trade=0.01,
            circuit_breaker=CircuitBreaker(),
        )
        qty_default = rm.calculate_qty(entry=100.0, stop_loss=99.0, leverage=1.0)
        qty_zero = rm.calculate_qty(entry=100.0, stop_loss=99.0, leverage=1.0, slippage_bps=0)
        assert qty_default == qty_zero


# ---------------------------------------------------------------------------
# Funding Cost Tracking in PnL
# ---------------------------------------------------------------------------

class TestFundingCostPnL:
    """Test that funding costs are included in PnL computation."""

    def test_compute_pnl_without_funding(self):
        from execution.pnl_engine import compute_pnl
        result = compute_pnl(
            effective_entry=100.0, exit_price=105.0,
            side="LONG", size_usd=1000.0, fee_bps=5,
        )
        assert result["pnl"] > 0
        assert result["funding_costs"] == 0.0

    def test_compute_pnl_with_funding_reduces_profit(self):
        from execution.pnl_engine import compute_pnl
        result_no_fund = compute_pnl(
            effective_entry=100.0, exit_price=105.0,
            side="LONG", size_usd=1000.0, fee_bps=5, funding_costs=0.0,
        )
        result_with_fund = compute_pnl(
            effective_entry=100.0, exit_price=105.0,
            side="LONG", size_usd=1000.0, fee_bps=5, funding_costs=5.0,
        )
        assert result_with_fund["pnl"] < result_no_fund["pnl"]
        assert result_with_fund["funding_costs"] == 5.0
        # Difference should be the funding cost
        assert result_no_fund["pnl"] - result_with_fund["pnl"] == pytest.approx(5.0, abs=0.01)

    def test_compute_pnl_funding_can_flip_outcome(self):
        from execution.pnl_engine import compute_pnl
        # Small profit that funding eats
        result = compute_pnl(
            effective_entry=100.0, exit_price=100.5,
            side="LONG", size_usd=1000.0, fee_bps=5,
            funding_costs=5.0,
        )
        # raw_pnl = (100.5 - 100) * 10 = 5.0
        # fees = 1000 * 0.0005 * 2 = 1.0
        # total_costs = 1.0 + 5.0 = 6.0
        # net_pnl = 5.0 - 6.0 = -1.0 → LOSS
        assert result["outcome"] == "LOSS"

    def test_position_has_funding_costs_field(self):
        from execution.position_manager import PositionManager
        pm = PositionManager()
        pos = pm.open_position("BTC", "LONG", 50000.0, 0.1, 49000.0, 52000.0, 55000.0)
        assert hasattr(pos, "funding_costs")
        assert pos.funding_costs == 0.0


# ---------------------------------------------------------------------------
# SL Breakeven Fee Buffer
# ---------------------------------------------------------------------------

class TestSLFeeBuffer:
    """Test that SL breakeven buffer covers round-trip fees."""

    def test_fee_buffer_uses_round_trip_fees(self):
        from execution.position_manager import PositionManager
        pm = PositionManager(taker_fee_bps=5)  # 5 bps each way
        pos = pm.open_position("BTC", "LONG", 50000.0, 0.1, 49000.0, 52000.0, 55000.0)
        # Simulate TP1 hit
        pm.update_price("BTC", 52000.0)
        # After TP1, SL should be entry + (entry * 5 * 2 / 10000) = 50000 + 50 = 50050
        # Old behavior was entry * 0.002 = 50000 + 100 = 50100
        # New buffer = 50000 * (5 * 2 / 10000) = 50000 * 0.001 = 50050
        pos = pm.positions["BTC"]
        if pos.state != "CLOSED":
            expected_buffer = 50000.0 * (5 * 2 / 10000.0)
            assert pos.sl >= 50000.0 + expected_buffer * 0.9  # Allow rounding

    def test_fee_buffer_short_side(self):
        from execution.position_manager import PositionManager
        pm = PositionManager(taker_fee_bps=5)
        pos = pm.open_position("ETH", "SHORT", 3000.0, 1.0, 3100.0, 2800.0, 2500.0)
        # Simulate TP1 hit
        pm.update_price("ETH", 2800.0)
        pos = pm.positions["ETH"]
        if pos.state != "CLOSED":
            expected_buffer = 3000.0 * (5 * 2 / 10000.0)
            assert pos.sl <= 3000.0 - expected_buffer * 0.9


# ---------------------------------------------------------------------------
# Backtest Slippage Model
# ---------------------------------------------------------------------------

class TestBacktestSlippage:
    """Test that backtest engine applies slippage to fills."""

    def test_slippage_config_exists(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert hasattr(config, "slippage_bps")
        assert config.slippage_bps >= 0

    def test_slippage_default_value(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.slippage_bps == 5  # 5 bps default


# ---------------------------------------------------------------------------
# Min Profit Threshold
# ---------------------------------------------------------------------------

class TestMinProfitThreshold:
    """Test minimum profit threshold configuration."""

    def test_min_profit_threshold_config_exists(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert hasattr(config, "min_profit_threshold_mult")
        assert config.min_profit_threshold_mult > 0

    def test_min_profit_check_logic(self):
        """Test the min profit check logic (to be wired into _process_symbol)."""
        taker_fee_bps = 5
        slippage_bps = 5
        min_profit_mult = 3.0

        # Total expected costs per side = (fee + slippage) in fraction
        total_cost_pct = (taker_fee_bps + slippage_bps) * 2 / 10000.0  # Round trip
        # For BTC at $50000, TP1 target
        entry = 50000.0
        tp1 = 50800.0
        target_pnl_pct = abs(tp1 - entry) / entry  # 1.6%

        # Should pass: 1.6% > 3 * 0.2% = 0.6%
        assert target_pnl_pct > min_profit_mult * total_cost_pct

        # Tight TP1 should fail
        tp1_tight = 50050.0
        tight_pnl_pct = abs(tp1_tight - entry) / entry  # 0.1%
        assert not (tight_pnl_pct > min_profit_mult * total_cost_pct)


# ---------------------------------------------------------------------------
# Config Profile (apply_profile)
# ---------------------------------------------------------------------------

class TestApplyProfile:
    """Test that apply_profile works correctly."""

    def test_apply_profile_paper(self):
        from trading_config import TradingConfig, apply_profile
        config = TradingConfig()
        config.environment = "paper"
        apply_profile(config)
        assert config.max_leverage == 25.0
        assert config.enable_smart_orders is False

    def test_apply_profile_live(self):
        from trading_config import TradingConfig, apply_profile
        config = TradingConfig()
        config.environment = "production"
        apply_profile(config)
        assert config.max_leverage == 25.0
        assert config.enable_smart_orders is True

    def test_apply_profile_env_override_takes_priority(self):
        from trading_config import TradingConfig, apply_profile
        os.environ["MAX_LEVERAGE"] = "15.0"
        try:
            config = TradingConfig()
            config.environment = "paper"
            apply_profile(config)
            # Env override should keep 15.0, not profile's 10.0
            assert config.max_leverage == 15.0
        finally:
            del os.environ["MAX_LEVERAGE"]


# ---------------------------------------------------------------------------
# Per-Symbol Overrides (get_symbol_param)
# ---------------------------------------------------------------------------

class TestSymbolOverrides:
    """Test per-symbol parameter overrides."""

    def test_get_symbol_param_uses_override(self):
        from trading_config import TradingConfig, get_symbol_param
        config = TradingConfig()
        # DOGE has max_leverage=20.0 in overrides
        val = get_symbol_param("DOGE", "max_leverage", config)
        assert val == 20.0

    def test_get_symbol_param_falls_back_to_global(self):
        from trading_config import TradingConfig, get_symbol_param
        config = TradingConfig()
        # Unknown symbol falls back to config default
        val = get_symbol_param("UNKNOWN_COIN", "max_leverage", config)
        assert val == config.max_leverage

    def test_get_symbol_param_risk_per_trade_falls_back(self):
        from trading_config import TradingConfig, get_symbol_param
        config = TradingConfig()
        # DOGE has no risk_per_trade override, falls back to global
        val = get_symbol_param("DOGE", "risk_per_trade", config)
        assert val == config.risk_per_trade

    def test_get_symbol_param_unknown_symbol_fallback(self):
        from trading_config import TradingConfig, get_symbol_param
        config = TradingConfig()
        # Unknown symbol falls back to config default
        val = get_symbol_param("UNKNOWN_COIN", "risk_per_trade", config)
        assert val == config.risk_per_trade


# ---------------------------------------------------------------------------
# New Config Params
# ---------------------------------------------------------------------------

class TestNewConfigParams:
    """Test all new config parameters added for profitability shield."""

    def test_max_portfolio_leverage(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.max_portfolio_leverage == 5.0

    def test_slippage_bps(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.slippage_bps == 5

    def test_min_profit_threshold_mult(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.min_profit_threshold_mult == 3.0

    def test_enable_funding_check(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.enable_funding_check is True

    def test_enable_correlation_check(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.enable_correlation_check is True

    def test_correlation_rejection_threshold(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.correlation_rejection_threshold == 0.8


# ---------------------------------------------------------------------------
# Funding Timer Integration
# ---------------------------------------------------------------------------

class TestFundingTimer:
    """Test should_close_before_funding logic."""

    def test_should_close_marginal_long_paying_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.2,  # Small profit
            funding_rate=0.001,  # 0.1% positive = longs pay
            leverage=5.0,
            side="LONG",
            minutes_to_funding=10,  # Close to funding
        )
        assert result is True

    def test_should_not_close_profitable_position(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=2.0,  # Strong profit
            funding_rate=0.001,
            leverage=5.0,
            side="LONG",
            minutes_to_funding=10,
        )
        assert result is False

    def test_should_not_close_when_far_from_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.2,
            funding_rate=0.001,
            leverage=5.0,
            side="LONG",
            minutes_to_funding=120,  # Far from funding
        )
        assert result is False

    def test_should_not_close_if_earning_funding(self):
        from execution.funding_timer import should_close_before_funding
        result = should_close_before_funding(
            pnl_pct=0.2,
            funding_rate=0.001,  # Positive = longs pay
            leverage=5.0,
            side="SHORT",  # Short earns when rate is positive
            minutes_to_funding=10,
        )
        assert result is False
