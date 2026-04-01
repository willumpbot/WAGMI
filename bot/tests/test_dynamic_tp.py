"""
Tests for Dynamic TP/SL Optimization using MFE data.

Tests cover:
1. MFE baseline computation per symbol
2. Regime adjustments (trending/ranging)
3. Volume adjustments (high volume widens TP)
4. Time-of-day adjustments (dead hours tighten TP)
5. ATR percentile adjustments
6. Safety checks (TP on correct side, minimum R:R)
7. Blend weight behavior (0=profile, 1=MFE)
8. Enable/disable via env var
9. Unknown symbols use defaults
10. Integration with trading_config
"""

import os
import pytest
from unittest.mock import patch

from execution.dynamic_tp import (
    DynamicTPOptimizer,
    DynamicTPResult,
    optimize_tp_sl,
    MFE_OPTIMAL_LEVELS,
    DEFAULT_MFE_LEVELS,
    _normalise_symbol,
    REGIME_TP_ADJUSTMENTS,
    HIGH_VOLUME_RATIO,
    DEAD_HOUR_START,
    DEAD_HOUR_END,
)


# ─── Symbol normalization ────────────────────────────────────────────

class TestSymbolNormalization:
    def test_plain_symbol(self):
        assert _normalise_symbol("BTC") == "BTC"

    def test_usdt_suffix(self):
        assert _normalise_symbol("BTC/USDT:USDT") == "BTC"

    def test_usdc_suffix(self):
        assert _normalise_symbol("SOL/USDC:USDC") == "SOL"

    def test_perp_suffix(self):
        assert _normalise_symbol("ETH-PERP") == "ETH"

    def test_lowercase(self):
        assert _normalise_symbol("hype") == "HYPE"


# ─── MFE baseline per symbol ─────────────────────────────────────────

class TestMFEBaseline:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)  # pure MFE

    def test_btc_baseline(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert result.enabled
        assert result.mfe_baseline_tp1_pct == 0.38
        assert result.mfe_baseline_sl_pct == 0.72

    def test_sol_baseline(self):
        result = self.opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            utc_hour=12,
        )
        assert result.mfe_baseline_tp1_pct == 0.51
        assert result.mfe_baseline_sl_pct == 0.96

    def test_eth_baseline(self):
        result = self.opt.optimize(
            symbol="ETH", side="BUY", entry=3500.0,
            current_tp1=3520.0, current_sl=3460.0,
            utc_hour=12,
        )
        assert result.mfe_baseline_tp1_pct == 0.44
        assert result.mfe_baseline_sl_pct == 0.90

    def test_hype_baseline(self):
        result = self.opt.optimize(
            symbol="HYPE", side="BUY", entry=25.0,
            current_tp1=25.3, current_sl=24.5,
            utc_hour=12,
        )
        assert result.mfe_baseline_tp1_pct == 0.78
        assert result.mfe_baseline_sl_pct == 1.34

    def test_unknown_symbol_uses_default(self):
        result = self.opt.optimize(
            symbol="DOGE", side="BUY", entry=0.10,
            current_tp1=0.105, current_sl=0.095,
            utc_hour=12,
        )
        assert result.mfe_baseline_tp1_pct == DEFAULT_MFE_LEVELS["tp1_pct"]
        assert result.mfe_baseline_sl_pct == DEFAULT_MFE_LEVELS["sl_pct"]

    def test_exchange_suffix_stripped(self):
        result = self.opt.optimize(
            symbol="BTC/USDT:USDT", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert result.mfe_baseline_tp1_pct == 0.38  # BTC data, not default


# ─── Buy vs Sell direction ───────────────────────────────────────────

class TestDirectionality:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)

    def test_buy_tp1_above_entry(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert result.tp1 > 100000.0

    def test_buy_sl_below_entry(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert result.sl < 100000.0

    def test_sell_tp1_below_entry(self):
        result = self.opt.optimize(
            symbol="BTC", side="SELL", entry=100000.0,
            current_tp1=99500.0, current_sl=100700.0,
            utc_hour=12,
        )
        assert result.tp1 < 100000.0

    def test_sell_sl_above_entry(self):
        result = self.opt.optimize(
            symbol="BTC", side="SELL", entry=100000.0,
            current_tp1=99500.0, current_sl=100700.0,
            utc_hour=12,
        )
        assert result.sl > 100000.0


# ─── Regime adjustments ──────────────────────────────────────────────

class TestRegimeAdjustments:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)
        self.base_kwargs = dict(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )

    def test_trending_widens_tp(self):
        neutral = self.opt.optimize(**self.base_kwargs, regime="unknown")
        trending = self.opt.optimize(**self.base_kwargs, regime="trending")
        # Trending TP1 should be wider (further from entry)
        assert trending.tp1 > neutral.tp1

    def test_ranging_tightens_tp(self):
        neutral = self.opt.optimize(**self.base_kwargs, regime="unknown")
        ranging = self.opt.optimize(**self.base_kwargs, regime="ranging")
        # Ranging TP1 should be tighter (closer to entry)
        assert ranging.tp1 < neutral.tp1

    def test_ranging_sell_tightens_tp(self):
        sell_kwargs = dict(
            symbol="BTC", side="SELL", entry=100000.0,
            current_tp1=99500.0, current_sl=100700.0,
            utc_hour=12,
        )
        neutral = self.opt.optimize(**sell_kwargs, regime="unknown")
        ranging = self.opt.optimize(**sell_kwargs, regime="ranging")
        # For SELL, tighter TP = closer to entry = higher price
        assert ranging.tp1 > neutral.tp1


# ─── Volume adjustments ─────────────────────────────────────────────

class TestVolumeAdjustments:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)

    def test_high_volume_widens_tp(self):
        normal = self.opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            volume_ratio=1.0, utc_hour=12,
        )
        high_vol = self.opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            volume_ratio=2.0, utc_hour=12,
        )
        assert high_vol.tp1 > normal.tp1

    def test_normal_volume_no_adjustment(self):
        result = self.opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            volume_ratio=1.0, utc_hour=12,
        )
        assert "high_volume" not in " ".join(result.adjustments)


# ─── Time-of-day adjustments ────────────────────────────────────────

class TestTimeOfDay:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)

    def test_dead_hours_tighten_tp(self):
        active = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=14,
        )
        dead = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=4,
        )
        assert dead.tp1 < active.tp1

    def test_non_dead_hours_no_adjustment(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=14,
        )
        assert "dead_hours" not in " ".join(result.adjustments)

    def test_dead_hour_boundaries(self):
        # Hour 3 is dead
        r3 = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=3,
        )
        assert "dead_hours" in " ".join(r3.adjustments)

        # Hour 6 is NOT dead (end is exclusive)
        r6 = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=6,
        )
        assert "dead_hours" not in " ".join(r6.adjustments)


# ─── ATR percentile adjustments ──────────────────────────────────────

class TestATRAdjustments:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)

    def test_high_atr_widens_tp(self):
        normal = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            atr=500.0, atr_p75=600.0, utc_hour=12,
        )
        high_atr = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            atr=700.0, atr_p75=600.0, utc_hour=12,
        )
        assert high_atr.tp1 > normal.tp1

    def test_no_atr_data_no_adjustment(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            atr=0.0, atr_p75=0.0, utc_hour=12,
        )
        assert "high_ATR" not in " ".join(result.adjustments)


# ─── Blend weight ────────────────────────────────────────────────────

class TestBlendWeight:
    def test_blend_0_uses_profile_only(self):
        opt = DynamicTPOptimizer(blend_weight=0.0)
        profile_tp1 = 100500.0
        profile_sl = 99300.0
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=profile_tp1, current_sl=profile_sl,
            utc_hour=12,
        )
        # With blend=0, should be exactly profile levels
        assert result.tp1 == profile_tp1
        assert result.sl == profile_sl

    def test_blend_1_uses_mfe_only(self):
        opt = DynamicTPOptimizer(blend_weight=1.0)
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        # TP1 should be entry * (1 + 0.38%) = 100380
        expected_tp1 = 100000.0 * (1 + 0.38 / 100)
        assert abs(result.tp1 - expected_tp1) < 1.0  # within $1

    def test_blend_05_is_midpoint(self):
        opt = DynamicTPOptimizer(blend_weight=0.5)
        profile_tp1 = 100800.0  # 0.8% above entry
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=profile_tp1, current_sl=99300.0,
            utc_hour=12,
        )
        mfe_tp1 = 100000.0 * (1 + 0.38 / 100)  # 100380
        expected = (mfe_tp1 + profile_tp1) / 2
        assert abs(result.tp1 - expected) < 1.0


# ─── Safety checks ──────────────────────────────────────────────────

class TestSafetyChecks:
    def setup_method(self):
        self.opt = DynamicTPOptimizer(blend_weight=1.0)

    def test_minimum_rr_enforced(self):
        """If MFE TP1 < SL distance, R:R floor should widen TP1."""
        # Create a scenario where SL is very wide but TP would be narrow
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100100.0, current_sl=98000.0,  # very wide SL
            utc_hour=12,
        )
        tp1_dist = abs(result.tp1 - 100000.0)
        sl_dist = abs(result.sl - 100000.0)
        if sl_dist > 0:
            assert tp1_dist / sl_dist >= 0.29  # at least ~0.3 R:R (MFE allows TP < SL for high-WR scalping)

    def test_zero_entry_returns_disabled(self):
        result = self.opt.optimize(
            symbol="BTC", side="BUY", entry=0.0,
            current_tp1=100.0, current_sl=99.0,
            utc_hour=12,
        )
        assert not result.enabled


# ─── Enable/disable ─────────────────────────────────────────────────

class TestEnableDisable:
    def test_disabled_returns_profile_levels(self):
        opt = DynamicTPOptimizer(blend_weight=0.6)
        opt.enabled = False
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert not result.enabled
        assert result.tp1 == 100500.0
        assert result.sl == 99300.0

    @patch.dict(os.environ, {"DYNAMIC_TP_ENABLED": "false"})
    def test_env_var_disables(self):
        opt = DynamicTPOptimizer()
        assert not opt.enabled


# ─── Module-level convenience function ───────────────────────────────

class TestModuleLevelFunction:
    def test_optimize_tp_sl_returns_result(self):
        result = optimize_tp_sl(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            utc_hour=12,
        )
        assert isinstance(result, DynamicTPResult)
        assert result.tp1 > 0
        assert result.sl > 0


# ─── Combined adjustments ───────────────────────────────────────────

class TestCombinedAdjustments:
    def test_trending_high_volume_widens_more(self):
        """Trending + high volume should widen TP more than either alone."""
        opt = DynamicTPOptimizer(blend_weight=1.0)
        base = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            regime="unknown", volume_ratio=1.0, utc_hour=12,
        )
        trending = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            regime="trending", volume_ratio=1.0, utc_hour=12,
        )
        combined = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            regime="trending", volume_ratio=2.0, utc_hour=12,
        )
        assert combined.tp1 > trending.tp1 > base.tp1

    def test_ranging_dead_hours_tightens_more(self):
        """Ranging + dead hours should tighten TP more than either alone."""
        opt = DynamicTPOptimizer(blend_weight=1.0)
        base = opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            regime="unknown", utc_hour=12,
        )
        ranging = opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            regime="ranging", utc_hour=12,
        )
        combined = opt.optimize(
            symbol="SOL", side="BUY", entry=150.0,
            current_tp1=151.0, current_sl=148.5,
            regime="ranging", utc_hour=4,
        )
        assert combined.tp1 < ranging.tp1 < base.tp1


# ─── trading_config integration ──────────────────────────────────────

class TestTradingConfigIntegration:
    def test_symbol_overrides_have_mfe_data(self):
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        btc = DEFAULT_SYMBOL_OVERRIDES.get("BTC")
        assert btc is not None
        assert btc.mfe_tp1_pct == 0.38
        assert btc.mfe_sl_pct == 0.72

    def test_sol_mfe_data(self):
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        sol = DEFAULT_SYMBOL_OVERRIDES.get("SOL")
        assert sol is not None
        assert sol.mfe_tp1_pct == 0.51
        assert sol.mfe_sl_pct == 0.96

    def test_hype_mfe_data(self):
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        hype = DEFAULT_SYMBOL_OVERRIDES.get("HYPE")
        assert hype is not None
        assert hype.mfe_tp1_pct == 0.78
        assert hype.mfe_sl_pct == 1.34

    def test_eth_mfe_data(self):
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        eth = DEFAULT_SYMBOL_OVERRIDES.get("ETH")
        assert eth is not None
        assert eth.mfe_tp1_pct == 0.44
        assert eth.mfe_sl_pct == 0.90

    def test_dynamic_tp_config_fields(self):
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert hasattr(cfg, 'dynamic_tp_enabled')
        assert hasattr(cfg, 'dynamic_tp_blend_weight')
        assert cfg.dynamic_tp_enabled is True
        assert cfg.dynamic_tp_blend_weight == 0.6


# ─── Adjustment logging ─────────────────────────────────────────────

class TestAdjustmentLogging:
    def test_adjustments_list_not_empty(self):
        opt = DynamicTPOptimizer(blend_weight=0.6)
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert len(result.adjustments) >= 2  # at least baseline + final

    def test_adjustments_contain_baseline(self):
        opt = DynamicTPOptimizer(blend_weight=0.6)
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert any("MFE baseline" in a for a in result.adjustments)

    def test_adjustments_contain_final(self):
        opt = DynamicTPOptimizer(blend_weight=0.6)
        result = opt.optimize(
            symbol="BTC", side="BUY", entry=100000.0,
            current_tp1=100500.0, current_sl=99300.0,
            utc_hour=12,
        )
        assert any("final:" in a for a in result.adjustments)
