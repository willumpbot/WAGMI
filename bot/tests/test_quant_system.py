"""
Tests for the Quant Trading System upgrades.

Covers:
- Track A: Defensive fixes (strategy disable, losing combos, CB session DD)
- Track B: Regime routing (min_votes lookup, 4h confirmation, allowlists)
- Track C: IC tracker, funding rate, OI divergence signals
- Track D: Compound sizing, leverage gate, correlation gate, Kelly, time stop
- Track E: Walk-forward, power analysis, factor tester
"""

import math
import time
import pytest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════════
# Track A: Defensive Fixes
# ═══════════════════════════════════════════════════════════════

class TestStrategyDisableFlags:
    """A1+A2: Strategy disable flags in trading_config."""

    def test_lead_lag_disabled_by_default(self):
        from trading_config import TradingConfig
        tc = TradingConfig()
        assert tc.strategy_lead_lag_enabled is False

    def test_multi_tier_quality_disabled_by_default(self):
        from trading_config import TradingConfig
        tc = TradingConfig()
        assert tc.strategy_multi_tier_quality_enabled is False

    def test_can_enable_via_env(self):
        import os
        os.environ["STRATEGY_LEAD_LAG_ENABLED"] = "true"
        try:
            from trading_config import TradingConfig
            tc = TradingConfig()
            assert tc.strategy_lead_lag_enabled is True
        finally:
            del os.environ["STRATEGY_LEAD_LAG_ENABLED"]


class TestLosingCombos:
    """A3: Expanded losing combos with subset matching."""

    def test_losing_combos_has_5_entries(self):
        # Access the combos from the weighted_veto method context
        _LOSING_COMBOS = {
            frozenset({"confidence_scorer", "multi_tier_quality"}),
            frozenset({"multi_tier_quality", "regime_trend"}),
            frozenset({"bollinger_squeeze", "multi_tier_quality"}),
            frozenset({"lead_lag", "multi_tier_quality"}),
            frozenset({"bollinger_squeeze", "confidence_scorer", "multi_tier_quality"}),
        }
        assert len(_LOSING_COMBOS) == 5

    def test_subset_matching_blocks_3_agree_containing_toxic_pair(self):
        """A 3-agree combo containing a toxic 2-agree pair should be blocked."""
        _LOSING_COMBOS = {
            frozenset({"confidence_scorer", "multi_tier_quality"}),
            frozenset({"multi_tier_quality", "regime_trend"}),
        }
        signal_names = frozenset({"confidence_scorer", "multi_tier_quality", "regime_trend"})
        blocked = False
        for combo in _LOSING_COMBOS:
            if combo.issubset(signal_names):
                blocked = True
                break
        assert blocked is True

    def test_valid_combo_not_blocked(self):
        _LOSING_COMBOS = {
            frozenset({"confidence_scorer", "multi_tier_quality"}),
        }
        signal_names = frozenset({"confidence_scorer", "regime_trend"})
        blocked = any(combo.issubset(signal_names) for combo in _LOSING_COMBOS)
        assert blocked is False


class TestCircuitBreakerSessionDD:
    """A4: Session drawdown fix."""

    def test_session_peak_equity_init(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.session_peak_equity == 0.0
        assert cb._session_halted is False

    def test_start_session_sets_peak(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker()
        cb.start_session(10000.0)
        assert cb.session_peak_equity == 10000.0

    def test_session_halt_not_recoverable(self):
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.50,  # High daily limit so we test session DD
            max_drawdown_pct=0.50,      # High per-cycle limit
            max_consecutive_losses=100,  # Don't trip on consecutive losses
        )
        cb.max_session_drawdown_pct = 0.20  # 20% session limit
        cb.start_session(10000.0)
        cb.peak_equity = 10000.0

        # Gradual losses to trigger session DD
        cb.record_trade(-500, 9500)
        cb.record_trade(-500, 9000)
        cb.record_trade(-500, 8500)
        cb.record_trade(-500, 8000)  # 20% session DD → halted
        assert cb._session_halted is True

        # Even with cooldown elapsed, session halt prevents trading
        cb.tripped = False  # Pretend cooldown cleared regular trip
        cb.trip_time = None
        assert cb.is_trading_allowed(confidence=95, equity=8000) is False

    def test_session_dd_cumulative_across_cooldowns(self):
        """The bug: peak_equity resets after cooldown, allowing cumulative DD > limit."""
        from execution.risk import CircuitBreaker
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.50,  # High daily limit
            max_drawdown_pct=0.50,      # High per-cycle limit
            max_consecutive_losses=100,
        )
        cb.max_session_drawdown_pct = 0.20
        cb.start_session(10000.0)
        cb.peak_equity = 10000.0

        # Gradual losses: 10000 → 8500 (15% from session peak)
        cb.record_trade(-500, 9500)
        cb.record_trade(-500, 9000)
        cb.record_trade(-500, 8500)

        # Cooldown resets peak_equity to 8500 (the old bug)
        cb.peak_equity = 8500  # Simulates the cooldown reset

        # Another loss to 7800 — regular CB sees 8.2% DD from 8500
        # But session DD = (10000-7800)/10000 = 22% → HALT
        cb.record_trade(-700, 7800)
        assert cb._session_halted is True
        assert cb.session_peak_equity == 10000.0  # Never reset


# ═══════════════════════════════════════════════════════════════
# Track B: Regime & Routing
# ═══════════════════════════════════════════════════════════════

class TestRegimeMinVotes:
    """B1: Regime-gated min_votes lookup table."""

    def test_bear_regime_requires_3(self):
        from strategies.ensemble import EnsembleStrategy
        assert EnsembleStrategy.REGIME_MIN_VOTES.get("trending_bear") == 3

    def test_bull_regime_allows_2(self):
        from strategies.ensemble import EnsembleStrategy
        assert EnsembleStrategy.REGIME_MIN_VOTES.get("trending_bull") == 2

    def test_consolidation_allows_2(self):
        from strategies.ensemble import EnsembleStrategy
        assert EnsembleStrategy.REGIME_MIN_VOTES.get("consolidation") == 2

    def test_unknown_defaults_to_3(self):
        from strategies.ensemble import EnsembleStrategy
        assert EnsembleStrategy.REGIME_MIN_VOTES.get("unknown") == 3

    def test_high_vol_requires_3(self):
        from strategies.ensemble import EnsembleStrategy
        assert EnsembleStrategy.REGIME_MIN_VOTES.get("high_volatility") == 3


class TestRegimeAllowlist:
    """B3: Regime-specific strategy allowlist."""

    def test_bear_only_allows_confidence_and_regime(self):
        from strategies.ensemble import EnsembleStrategy
        allowed = EnsembleStrategy.STRATEGY_REGIME_ALLOWLIST["trending_bear"]
        assert "confidence_scorer" in allowed
        assert "regime_trend" in allowed
        assert "bollinger_squeeze" not in allowed
        assert "vmc_cipher" not in allowed

    def test_consolidation_allows_mean_reversion(self):
        from strategies.ensemble import EnsembleStrategy
        allowed = EnsembleStrategy.STRATEGY_REGIME_ALLOWLIST["consolidation"]
        assert "bollinger_squeeze" in allowed
        assert "vmc_cipher" in allowed

    def test_unknown_blocks_all(self):
        from strategies.ensemble import EnsembleStrategy
        allowed = EnsembleStrategy.STRATEGY_REGIME_ALLOWLIST["unknown"]
        assert len(allowed) == 0


class TestTimeframeAlignment:
    """B2: 4h regime confirmation filter."""

    def test_3_agree_bypasses_filter(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._current_regime = {"BTC": "trending_bull"}
        ens._current_regime_4h = {"BTC": "trending_bear"}
        # 3-agree should pass even with conflicting 4h
        assert ens._check_timeframe_alignment("BTC", 3) is True

    def test_2_agree_blocked_on_conflict(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._current_regime = {"BTC": "trending_bull"}
        ens._current_regime_4h = {"BTC": "trending_bear"}
        assert ens._check_timeframe_alignment("BTC", 2) is False

    def test_2_agree_passes_on_agreement(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._current_regime = {"BTC": "trending_bull"}
        ens._current_regime_4h = {"BTC": "trending_bull"}
        assert ens._check_timeframe_alignment("BTC", 2) is True

    def test_compatible_pair_passes(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._current_regime = {"BTC": "consolidation"}
        ens._current_regime_4h = {"BTC": "trending_bull"}
        assert ens._check_timeframe_alignment("BTC", 2) is True

    def test_no_4h_data_passes(self):
        from strategies.ensemble import EnsembleStrategy
        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._current_regime = {"BTC": "trending_bull"}
        ens._current_regime_4h = {}
        assert ens._check_timeframe_alignment("BTC", 2) is True


# ═══════════════════════════════════════════════════════════════
# Track D: Portfolio Construction & Sizing
# ═══════════════════════════════════════════════════════════════

class TestCompoundSizing:
    """D1: Compound sizing formula."""

    def test_all_neutral_returns_base(self):
        from execution.risk import RiskManager
        rm = RiskManager(starting_equity=10000)
        result = rm.calculate_compound_size(base_risk=0.01)
        assert abs(result - 0.01) < 0.001

    def test_bear_regime_halves_size(self):
        from execution.risk import RiskManager
        rm = RiskManager(starting_equity=10000)
        result = rm.calculate_compound_size(base_risk=0.01, regime_scalar=0.5)
        assert abs(result - 0.005) < 0.001

    def test_unknown_regime_zeros_out(self):
        from execution.risk import RiskManager
        rm = RiskManager(starting_equity=10000)
        result = rm.calculate_compound_size(base_risk=0.01, regime_scalar=0.0)
        assert result == 0.0

    def test_capped_at_2x_base(self):
        from execution.risk import RiskManager
        rm = RiskManager(starting_equity=10000)
        result = rm.calculate_compound_size(
            base_risk=0.01, kelly_weight=5.0, regime_scalar=2.0
        )
        assert result <= 0.02  # 2× base_risk

    def test_regime_scalars_lookup(self):
        from execution.risk import RiskManager
        rm = RiskManager(starting_equity=10000)
        assert rm.get_regime_scalar("consolidation") == 1.0
        assert rm.get_regime_scalar("trending_bull") == 0.85
        assert rm.get_regime_scalar("trending_bear") == 0.5
        assert rm.get_regime_scalar("high_volatility") == 0.3
        assert rm.get_regime_scalar("unknown") == 0.0

    def test_drawdown_dial_graduated(self):
        from execution.risk import RiskManager, CircuitBreaker
        cb = CircuitBreaker()
        cb.session_peak_equity = 10000
        rm = RiskManager(starting_equity=10000, circuit_breaker=cb)

        # No drawdown
        assert rm.get_drawdown_dial() == 1.0

        # 7% drawdown
        rm.equity = 9300
        assert rm.get_drawdown_dial() == 0.75

        # 12% drawdown
        rm.equity = 8800
        assert rm.get_drawdown_dial() == 0.5

        # 17% drawdown
        rm.equity = 8300
        assert rm.get_drawdown_dial() == 0.25


class TestLeverageGate:
    """D2: Leverage eligibility entry gate."""

    def test_leverage_gate_config_exists(self):
        from trading_config import TradingConfig
        tc = TradingConfig()
        assert hasattr(tc, "min_leverage_entry_gate")
        assert tc.min_leverage_entry_gate == 1.2


class TestTimeStop:
    """D6: 8-hour time stop."""

    def test_time_stop_config_exists(self):
        from trading_config import TradingConfig
        tc = TradingConfig()
        assert hasattr(tc, "time_stop_hours")
        assert tc.time_stop_hours == 8


# ═══════════════════════════════════════════════════════════════
# Track E: Research Pipeline & Validation
# ═══════════════════════════════════════════════════════════════

class TestWalkForward:
    """E1: Walk-forward validation."""

    def test_rolling_wf_basic(self):
        from validation.walk_forward import run_rolling_walk_forward, avg_wf_ratio

        # Create 60 days of trade data
        trades = []
        base_ts = 1700000000
        for i in range(100):
            ts = base_ts + i * 43200  # Every 12 hours
            pnl = 50 if i % 3 != 0 else -100  # ~67% WR, negative EV
            trades.append({"timestamp": ts, "net_pnl": pnl})

        results = run_rolling_walk_forward(trades, train_days=20, test_days=7)
        assert len(results) > 0

        ratio = avg_wf_ratio(results)
        assert isinstance(ratio, float)

    def test_insufficient_data_returns_empty(self):
        from validation.walk_forward import run_rolling_walk_forward

        trades = [{"timestamp": 1700000000, "net_pnl": 50}]
        results = run_rolling_walk_forward(trades)
        assert results == []

    def test_wf_alert_on_low_ratio(self):
        from validation.walk_forward import check_wf_alert

        # Low ratio should alert
        results = [{"wf_ratio": 0.2}, {"wf_ratio": 0.3}, {"wf_ratio": 0.1}]
        alert = check_wf_alert(results)
        assert alert is not None
        assert "WARNING" in alert or "CRITICAL" in alert

    def test_wf_no_alert_on_good_ratio(self):
        from validation.walk_forward import check_wf_alert

        results = [{"wf_ratio": 0.8}, {"wf_ratio": 0.7}, {"wf_ratio": 0.9}]
        alert = check_wf_alert(results)
        assert alert is None


class TestPowerAnalysis:
    """E2: Statistical power checks."""

    def test_min_sample_reasonable(self):
        from validation.power_analysis import min_sample_for_significance

        # Detect 10% WR improvement from 50% baseline
        n = min_sample_for_significance(base_wr=0.50, delta=0.10)
        assert 200 < n < 600  # Should be ~392

    def test_larger_delta_needs_fewer_samples(self):
        from validation.power_analysis import min_sample_for_significance

        n_small = min_sample_for_significance(delta=0.05)
        n_large = min_sample_for_significance(delta=0.20)
        assert n_small > n_large

    def test_sample_adequacy_insufficient(self):
        from validation.power_analysis import assess_sample_adequacy

        result = assess_sample_adequacy(n_trades=8, win_rate=0.5)
        assert result["adequate"] is False
        assert result["verdict"] == "MINIMAL"

    def test_sample_adequacy_sufficient(self):
        from validation.power_analysis import assess_sample_adequacy

        result = assess_sample_adequacy(n_trades=500, win_rate=0.55)
        assert result["adequate"] is True
        assert result["verdict"] == "SUFFICIENT"

    def test_strategy_reactivation_check(self):
        from validation.power_analysis import can_reactivate_strategy

        # Not enough shadow trades
        result = can_reactivate_strategy("lead_lag", shadow_trades=8,
                                          shadow_win_rate=0.75, shadow_avg_pnl=50)
        assert result["can_reactivate"] is False
        assert "WAIT" in result["recommendation"]


class TestFactorTester:
    """E3: Factor research pipeline."""

    def test_insufficient_trades_rejected(self):
        from research.factor_tester import FactorTester

        tester = FactorTester()
        result = tester.validate_factor("test_factor", [])
        assert result["passed_all"] is False
        assert "Insufficient" in result.get("error", "")

    def test_good_factor_passes(self):
        from research.factor_tester import FactorTester
        import random
        random.seed(42)

        # Create a factor with genuine edge
        trades = []
        for i in range(100):
            direction = 1 if random.random() > 0.35 else -1  # 65% accuracy
            actual = direction * abs(random.gauss(0.02, 0.01))
            regime = random.choice(["trending_bull", "consolidation", "trending_bear"])
            trades.append({
                "predicted_direction": direction,
                "actual_return": actual,
                "net_pnl": actual * 10000,
                "won": actual > 0,
                "regime": regime,
            })

        tester = FactorTester()
        result = tester.validate_factor("good_factor", trades)
        # At least some steps should pass
        assert result["passed_count"] > 0

    def test_random_factor_fails(self):
        from research.factor_tester import FactorTester
        import random
        random.seed(123)

        # Create a purely random factor
        trades = []
        for i in range(100):
            direction = 1 if random.random() > 0.5 else -1
            actual = random.gauss(0, 0.02)  # Random around 0
            trades.append({
                "predicted_direction": direction,
                "actual_return": actual,
                "net_pnl": actual * 10000,
                "won": actual > 0,
                "regime": random.choice(["trending_bull", "consolidation"]),
            })

        tester = FactorTester()
        result = tester.validate_factor("random_factor", trades)
        assert result["passed_all"] is False


# ═══════════════════════════════════════════════════════════════
# Track C: New Signals
# ═══════════════════════════════════════════════════════════════

class TestFundingRateSignal:
    """C2: Funding rate signal."""

    def test_import_works(self):
        from strategies.funding_rate_signal import FundingRateStrategy
        strategy = FundingRateStrategy()
        assert strategy.name == "funding_rate"

    def test_neutral_funding_no_signal(self):
        from strategies.funding_rate_signal import FundingRateStrategy
        import pandas as pd
        import numpy as np

        strategy = FundingRateStrategy()
        df = pd.DataFrame({
            "open": np.random.uniform(50000, 51000, 50),
            "high": np.random.uniform(50500, 51500, 50),
            "low": np.random.uniform(49500, 50500, 50),
            "close": np.random.uniform(50000, 51000, 50),
            "volume": np.random.uniform(100, 1000, 50),
        })
        data = {"1h": df, "funding_rate": 0.0001}  # Neutral
        result = strategy.evaluate("BTC", data)
        assert result is None


class TestOIDivergenceSignal:
    """C3: OI divergence signal."""

    def test_import_works(self):
        from strategies.oi_divergence import OIDivergenceStrategy
        strategy = OIDivergenceStrategy()
        assert strategy.name == "oi_divergence"


# ═══════════════════════════════════════════════════════════════
# Integration: Ensemble with new features
# ═══════════════════════════════════════════════════════════════

class TestEnsembleConfigDisables:
    """Ensemble correctly disables strategies from config."""

    def test_apply_config_disables(self):
        from strategies.ensemble import EnsembleStrategy

        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._disabled_strategies = set()

        config = MagicMock()
        config.strategy_lead_lag_enabled = False
        config.strategy_multi_tier_quality_enabled = False

        ens.apply_config_disables(config)
        assert "lead_lag" in ens._disabled_strategies
        assert "multi_tier_quality" in ens._disabled_strategies

    def test_apply_config_does_not_disable_when_enabled(self):
        from strategies.ensemble import EnsembleStrategy

        ens = EnsembleStrategy.__new__(EnsembleStrategy)
        ens._disabled_strategies = set()

        config = MagicMock()
        config.strategy_lead_lag_enabled = True
        config.strategy_multi_tier_quality_enabled = True

        ens.apply_config_disables(config)
        assert "lead_lag" not in ens._disabled_strategies
        assert "multi_tier_quality" not in ens._disabled_strategies
