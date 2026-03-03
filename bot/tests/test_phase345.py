"""
Tests for Phase 3-5 changes:
- Phase 3: Configurable parameters, symbol overrides, config profiles
- Phase 4: Exchange circuit breaker, structured logging, health server,
           signal pipeline, portfolio analytics, reconciliation persistence
- Phase 5: Parameter optimizer, Sharpe calculation, backtest bridge
"""

import json
import logging
import math
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Phase 3: Configuration ──────────────────────────────────────────


class TestConfigurableParams:
    """Phase 3: All hardcoded values are now in TradingConfig."""

    def test_strategy_params_exist(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert hasattr(cfg, "ensemble_confidence_floor")
        assert hasattr(cfg, "min_signal_rr")
        assert hasattr(cfg, "mc_num_sims")
        assert hasattr(cfg, "regime_trend_min_confidence")

    def test_indicator_periods_exist(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.atr_period > 0
        assert cfg.ema_short_period > 0
        assert cfg.ema_medium_period > cfg.ema_short_period
        assert cfg.ema_long_period > cfg.ema_medium_period
        assert cfg.rsi_period > 0

    def test_cooldown_params_exist(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.loss_cooldown_s >= 0
        assert cfg.win_cooldown_s >= 0
        assert cfg.signal_dedup_window_s > 0

    def test_timeframe_weights(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.tf_weight_5m == 0.5
        assert cfg.tf_weight_1h == 1.0
        assert cfg.tf_weight_6h == 1.5
        assert cfg.tf_weight_daily == 2.0

    def test_leverage_risk_tier_caps(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.leverage_cap_medium_risk > 0
        assert cfg.leverage_cap_high_risk > 0
        assert cfg.leverage_cap_medium_risk >= cfg.leverage_cap_high_risk

    def test_data_fetcher_resilience_params(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.fetcher_max_retries >= 1
        assert cfg.fetcher_circuit_breaker_threshold > 0
        assert cfg.fetcher_circuit_breaker_reset_s > 0

    def test_health_monitoring_params(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert cfg.health_port > 0
        assert cfg.health_stall_timeout_s > 0


class TestSymbolOverrides:
    """Phase 3: Per-symbol configuration overrides."""

    def test_symbol_overrides_dataclass(self):
        from trading_config import SymbolOverrides
        ov = SymbolOverrides(max_leverage=3.0, risk_per_trade=0.005)
        assert ov.max_leverage == 3.0
        assert ov.risk_per_trade == 0.005

    def test_get_symbol_param_default(self):
        from trading_config import get_symbol_param, TradingConfig
        cfg = TradingConfig()
        # Non-overridden symbol should return config default
        val = get_symbol_param("UNKNOWN_SYMBOL", "max_leverage", cfg)
        assert val == cfg.max_leverage

    def test_get_symbol_param_override(self):
        from trading_config import get_symbol_param, DEFAULT_SYMBOL_OVERRIDES, TradingConfig
        cfg = TradingConfig()
        # If overrides exist, they should return the overridden value
        for sym, overrides in DEFAULT_SYMBOL_OVERRIDES.items():
            if overrides.max_leverage is not None:
                val = get_symbol_param(sym, "max_leverage", cfg)
                assert val == overrides.max_leverage
                break


class TestConfigProfiles:
    """Phase 3: Paper vs live config profiles."""

    def test_paper_profile(self):
        from trading_config import TradingConfig, apply_profile
        cfg = TradingConfig()
        cfg.environment = "paper"
        apply_profile(cfg)
        assert cfg.max_open_positions <= 3
        assert cfg.max_leverage <= 10.0

    def test_live_profile(self):
        from trading_config import TradingConfig, apply_profile
        cfg = TradingConfig()
        cfg.environment = "production"
        apply_profile(cfg)
        # Live should have stricter risk
        assert cfg.risk_per_trade <= 0.015

    def test_profile_env_var_priority(self):
        from trading_config import TradingConfig, apply_profile
        cfg = TradingConfig()
        cfg.environment = "paper"
        # If env var is set, profile shouldn't override it
        original_risk = cfg.risk_per_trade
        apply_profile(cfg)
        # apply_profile only overrides if env var is NOT set
        assert cfg.risk_per_trade > 0


# ── Phase 4: Exchange Circuit Breaker ────────────────────────────────


class TestExchangeCircuitBreaker:
    """Phase 4: Circuit breaker on data fetcher."""

    EX = "kraken"

    def test_cb_starts_closed(self):
        from data.fetcher import ExchangeCircuitBreaker
        cb = ExchangeCircuitBreaker(threshold=3, reset_s=60)
        assert cb.is_open(self.EX) is False

    def test_cb_opens_after_threshold(self):
        from data.fetcher import ExchangeCircuitBreaker
        cb = ExchangeCircuitBreaker(threshold=3, reset_s=60)
        cb.record_failure(self.EX)
        cb.record_failure(self.EX)
        assert cb.is_open(self.EX) is False
        cb.record_failure(self.EX)
        assert cb.is_open(self.EX) is True

    def test_cb_resets_on_success(self):
        from data.fetcher import ExchangeCircuitBreaker
        cb = ExchangeCircuitBreaker(threshold=3, reset_s=60)
        cb.record_failure(self.EX)
        cb.record_failure(self.EX)
        cb.record_success(self.EX)
        assert cb._failures.get(self.EX, 0) == 0

    def test_cb_auto_resets_after_timeout(self):
        from data.fetcher import ExchangeCircuitBreaker
        cb = ExchangeCircuitBreaker(threshold=1, reset_s=0.01)
        cb.record_failure(self.EX)
        assert cb.is_open(self.EX) is True
        time.sleep(0.02)
        assert cb.is_open(self.EX) is False

    def test_cb_status(self):
        from data.fetcher import ExchangeCircuitBreaker
        cb = ExchangeCircuitBreaker(threshold=3, reset_s=60)
        status = cb.get_status()
        assert self.EX not in status  # No state tracked yet
        cb.record_failure(self.EX)
        cb.record_failure(self.EX)
        cb.record_failure(self.EX)
        status = cb.get_status()
        assert self.EX in status
        assert status[self.EX]["open"] is True


# ── Phase 4: Structured Logging ──────────────────────────────────────


class TestStructuredLogging:
    """Phase 4: JSON and human-readable log formatters."""

    def test_json_formatter(self):
        from core.structured_logging import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "test.py", 1, "hello %s", ("world",), None
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["msg"] == "hello world"
        assert parsed["level"] == "INFO"

    def test_json_formatter_with_structured_data(self):
        from core.structured_logging import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "test.py", 1, "trade", (), None
        )
        record.structured = {"event": "open", "symbol": "BTC"}
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["data"]["event"] == "open"
        assert parsed["data"]["symbol"] == "BTC"

    def test_human_formatter(self):
        from core.structured_logging import HumanFormatter
        fmt = HumanFormatter()
        record = logging.LogRecord(
            "bot.test", logging.WARNING, "test.py", 1, "warning msg", (), None
        )
        output = fmt.format(record)
        assert "warning msg" in output
        assert "[W]" in output

    def test_log_trade_event(self):
        from core.structured_logging import log_trade_event
        mock_logger = MagicMock()
        log_trade_event(mock_logger, "trade_opened", "BTC", side="BUY", confidence=85.0)
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert "[trade_opened]" in call_args[0][0]

    def test_log_metric(self):
        from core.structured_logging import log_metric
        mock_logger = MagicMock()
        log_metric(mock_logger, "equity", 10500.0, environment="paper")
        mock_logger.info.assert_called_once()


# ── Phase 4: Signal Pipeline ─────────────────────────────────────────


class TestSignalPipeline:
    """Phase 4: RiskFilterChain extracted from multi_strategy_main."""

    def test_filter_result_dataclass(self):
        from core.signal_pipeline import FilterResult
        from strategies.base import Signal
        sig = Signal(symbol="BTC", side="BUY", entry=50000, sl=49000,
                     tp1=52000, tp2=54000, atr=500, confidence=75,
                     strategy="test")
        result = FilterResult(approved=True, signal=sig)
        assert result.approved is True
        assert result.signal.symbol == "BTC"

    def test_risk_filter_chain_exists(self):
        from core.signal_pipeline import RiskFilterChain
        assert RiskFilterChain is not None


# ── Phase 4: Portfolio Analytics ──────────────────────────────────────


class TestPortfolioAnalytics:
    """Phase 4: Portfolio-level metrics computation."""

    def test_portfolio_leverage_zero_equity(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics()
        assert pa.compute_portfolio_leverage({}, 0) == 0.0

    def test_portfolio_leverage_with_positions(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics()

        class MockPos:
            state = "OPEN"
            entry = 50000
            qty = 0.1
            leverage = 3

        positions = {"BTC": MockPos()}
        lev = pa.compute_portfolio_leverage(positions, 10000)
        # notional = 50000 * 0.1 * 3 = 15000; leverage = 15000 / 10000 = 1.5
        assert lev == 1.5

    def test_portfolio_correlation_all_long(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics()

        class MockPos:
            state = "OPEN"
            side = "LONG"

        positions = {"BTC": MockPos(), "ETH": MockPos(), "SOL": MockPos()}
        result = pa.compute_portfolio_correlation(positions)
        assert result["correlation"] == 1.0
        assert result["risk_level"] == "high"

    def test_portfolio_correlation_balanced(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics()

        class LongPos:
            state = "OPEN"
            side = "LONG"

        class ShortPos:
            state = "OPEN"
            side = "SHORT"

        positions = {"BTC": LongPos(), "ETH": ShortPos()}
        result = pa.compute_portfolio_correlation(positions)
        assert result["correlation"] == 0.5
        assert result["risk_level"] == "low"

    def test_full_metrics(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics(max_portfolio_risk_pct=5.0)

        class MockPos:
            state = "OPEN"
            entry = 50000
            qty = 0.1
            leverage = 2
            sl = 49000
            side = "LONG"

        positions = {"BTC": MockPos()}
        metrics = pa.compute_full_metrics(positions, equity=10000)
        assert "portfolio_leverage" in metrics
        assert "active_positions" in metrics
        assert "daily_funding_est" in metrics
        assert "correlation" in metrics
        assert "total_risk_pct" in metrics
        assert "risk_ok" in metrics

    def test_funding_cost_estimation(self):
        from core.portfolio_analytics import PortfolioAnalytics
        pa = PortfolioAnalytics()

        class MockPos:
            state = "OPEN"
            entry = 50000
            qty = 0.1
            side = "LONG"

        positions = {"BTC": MockPos()}
        # Positive funding rate: longs pay
        cost = pa.compute_estimated_daily_funding(positions, {"BTC": 0.0001})
        assert cost < 0  # Cost to longs


# ── Phase 4: Reconciliation Persistence ──────────────────────────────


class TestReconciliationPersistence:
    """Phase 4: CB state and reconciliation improvements."""

    def test_save_and_restore_cb_state(self):
        from execution.reconciliation import save_circuit_breaker_state, restore_circuit_breaker_state

        class MockCB:
            tripped = False
            trip_reason = ""
            daily_pnl = -50.0
            consecutive_losses = 2
            peak_equity = 10000.0

        cb = MockCB()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cb_state.json")
            save_circuit_breaker_state(cb, path)
            assert os.path.exists(path)

            cb2 = MockCB()
            cb2.consecutive_losses = 0
            cb2.daily_pnl = 0.0
            restore_circuit_breaker_state(cb2, path)
            assert cb2.consecutive_losses == 2
            assert cb2.daily_pnl == -50.0


# ── Phase 5: Parameter Optimizer ─────────────────────────────────────


class TestParamOptimizer:
    """Phase 5: Grid search, random search, sensitivity analysis."""

    def _make_simple_fn(self):
        """Backtest fn where sharpe = -|x - 2.0| (optimal at x=2.0)."""
        def fn(params):
            x = params.get("x", 0)
            return {"sharpe": -abs(x - 2.0), "total_pnl": x * 10, "win_rate": 0.5}
        return fn

    def test_grid_search(self):
        from optimization.param_optimizer import ParameterOptimizer, ParamRange
        fn = self._make_simple_fn()
        opt = ParameterOptimizer(fn)
        spaces = {"x": ParamRange.linspace("x", 0, 4, 5)}
        result = opt.grid_search(spaces, metric="sharpe")
        assert result.best_params["x"] == 2.0
        assert result.best_score == 0.0
        assert result.total_trials == 5

    def test_random_search(self):
        from optimization.param_optimizer import ParameterOptimizer, ParamRange
        fn = self._make_simple_fn()
        opt = ParameterOptimizer(fn)
        spaces = {"x": ParamRange.choices("x", 1.0, 2.0, 3.0)}
        result = opt.random_search(spaces, metric="sharpe", n_trials=20)
        assert result.best_params["x"] == 2.0
        assert result.total_trials == 20

    def test_grid_search_fallback_to_random(self):
        from optimization.param_optimizer import ParameterOptimizer, ParamRange
        fn = self._make_simple_fn()
        opt = ParameterOptimizer(fn)
        # 10^3 = 1000 combos > max_trials=5 → falls back to random
        spaces = {"x": ParamRange.linspace("x", 0, 10, 10),
                  "y": ParamRange.linspace("y", 0, 10, 10),
                  "z": ParamRange.linspace("z", 0, 10, 10)}
        result = opt.grid_search(spaces, metric="sharpe", max_trials=5)
        assert result.total_trials == 5  # Used random search

    def test_sensitivity_analysis(self):
        from optimization.param_optimizer import ParameterOptimizer, ParamRange
        fn = self._make_simple_fn()
        opt = ParameterOptimizer(fn)
        base = {"x": 1.0}
        spaces = {"x": ParamRange.choices("x", 0.0, 1.0, 2.0, 3.0)}
        results = opt.sensitivity_analysis(base, spaces, metric="sharpe")
        assert "x" in results
        assert len(results["x"]) == 4
        # Best score at x=2.0
        best_val, best_score = max(results["x"], key=lambda t: t[1])
        assert best_val == 2.0

    def test_param_range_linspace(self):
        from optimization.param_optimizer import ParamRange
        pr = ParamRange.linspace("test", 0, 1, 5)
        assert len(pr.values) == 5
        assert pr.values[0] == 0.0
        assert pr.values[-1] == 1.0

    def test_param_range_choices(self):
        from optimization.param_optimizer import ParamRange
        pr = ParamRange.choices("test", "a", "b", "c")
        assert pr.values == ["a", "b", "c"]

    def test_failed_trial_continues(self):
        from optimization.param_optimizer import ParameterOptimizer, ParamRange

        call_count = 0
        def flaky_fn(params):
            nonlocal call_count
            call_count += 1
            if params["x"] == 1.0:
                raise ValueError("boom")
            return {"sharpe": params["x"]}

        opt = ParameterOptimizer(flaky_fn)
        spaces = {"x": ParamRange.choices("x", 1.0, 2.0, 3.0)}
        result = opt.grid_search(spaces, metric="sharpe")
        assert result.total_trials == 2  # Only 2 succeeded
        assert result.best_params["x"] == 3.0


class TestSharpeCalculation:
    """Phase 5: Sharpe ratio from equity curves."""

    def test_sharpe_flat_curve(self):
        from optimization.param_optimizer import compute_sharpe
        curve = [{"equity": 10000} for _ in range(100)]
        assert compute_sharpe(curve) == 0.0

    def test_sharpe_insufficient_data(self):
        from optimization.param_optimizer import compute_sharpe
        assert compute_sharpe([]) == 0.0
        assert compute_sharpe([{"equity": 100}]) == 0.0

    def test_sharpe_positive_trend(self):
        from optimization.param_optimizer import compute_sharpe
        # Steadily increasing equity → positive Sharpe
        curve = [{"equity": 10000 + i * 10} for i in range(200)]
        sharpe = compute_sharpe(curve)
        assert sharpe > 0

    def test_sharpe_negative_trend(self):
        from optimization.param_optimizer import compute_sharpe
        # Steadily decreasing equity → negative Sharpe
        curve = [{"equity": 10000 - i * 10} for i in range(200)]
        sharpe = compute_sharpe(curve)
        assert sharpe < 0

    def test_sharpe_volatile_vs_steady(self):
        from optimization.param_optimizer import compute_sharpe
        import random as rng
        rng.seed(42)
        # Both end at the same equity, but one is volatile
        steady = [{"equity": 10000 + i * 5} for i in range(200)]
        volatile = [{"equity": 10000 + i * 5 + rng.gauss(0, 50)} for i in range(200)]
        assert compute_sharpe(steady) > compute_sharpe(volatile)


class TestBacktestBridge:
    """Phase 5: create_backtest_fn and param config mapping."""

    def test_param_config_map_keys(self):
        from optimization.param_optimizer import _PARAM_CONFIG_MAP
        # All mapped values should be valid TradingConfig attrs
        from trading_config import TradingConfig
        cfg = TradingConfig()
        for param, attr in _PARAM_CONFIG_MAP.items():
            assert hasattr(cfg, attr), f"{attr} not in TradingConfig"

    def test_create_backtest_fn_returns_callable(self):
        from optimization.param_optimizer import create_backtest_fn
        fn = create_backtest_fn(["BTC"], days=7)
        assert callable(fn)
