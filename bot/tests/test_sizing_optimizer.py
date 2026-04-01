"""Tests for the dynamic sizing optimizer (Kelly + compound curves)."""
import pytest
from execution.sizing_optimizer import (
    SizingOptimizer,
    SetupStats,
    CompoundTier,
    OptimalSizing,
    _COMPOUND_TIERS,
    _DEFAULT_PRIORS,
)


class TestKellyFraction:
    """Test Kelly criterion calculations."""

    def test_kelly_with_prior_hype_buy(self):
        """HYPE BUY prior: 52% WR, 1.34:1 payoff → positive Kelly (edge weakening)."""
        opt = SizingOptimizer()
        kelly, wr, payoff = opt.kelly_fraction("HYPE_BUY")
        assert kelly > 0.10  # Positive edge but weaker than before
        assert wr == 0.52
        assert payoff == 1.34

    def test_kelly_with_prior_hype_sell(self):
        """HYPE SELL prior: 7% WR → near-zero Kelly."""
        opt = SizingOptimizer()
        kelly, wr, payoff = opt.kelly_fraction("HYPE_SELL")
        assert kelly == 0.0  # Negative edge

    def test_kelly_with_data(self):
        """After recording outcomes, Kelly uses real data."""
        opt = SizingOptimizer(min_trades_for_kelly=5)
        # Record 8 wins, 2 losses (80% WR)
        for _ in range(8):
            opt.record_outcome("TEST_SETUP", True, 3.0)
        for _ in range(2):
            opt.record_outcome("TEST_SETUP", False, 2.0)

        kelly, wr, payoff = opt.kelly_fraction("TEST_SETUP")
        assert abs(wr - 0.80) < 0.01
        assert payoff == 3.0 / 2.0  # avg_win / avg_loss
        assert kelly > 0.3  # Strong edge = high Kelly

    def test_kelly_blends_prior_with_small_data(self):
        """With < min_trades, blend prior and data."""
        opt = SizingOptimizer(min_trades_for_kelly=10)
        # Only 3 trades (below threshold)
        for _ in range(3):
            opt.record_outcome("HYPE_BUY", True, 4.0)

        kelly, wr, payoff = opt.kelly_fraction("HYPE_BUY")
        # Should be between prior (52%) and data (100%)
        assert 0.52 < wr < 1.0

    def test_kelly_capped_at_half(self):
        """Kelly should never exceed the cap (default 50%)."""
        opt = SizingOptimizer(min_trades_for_kelly=5)
        # Perfect record (100% WR with huge payoff)
        for _ in range(10):
            opt.record_outcome("PERFECT", True, 10.0)

        kelly, wr, payoff = opt.kelly_fraction("PERFECT")
        assert kelly <= 0.5

    def test_kelly_zero_for_losing_setup(self):
        """Setup with 0% WR should have Kelly = 0."""
        opt = SizingOptimizer(min_trades_for_kelly=5)
        for _ in range(10):
            opt.record_outcome("LOSER", False, 2.0)

        kelly, wr, payoff = opt.kelly_fraction("LOSER")
        assert kelly == 0.0

    def test_unknown_setup_uses_neutral_prior(self):
        """Unknown setup gets 50% WR, 1.5:1 payoff prior."""
        opt = SizingOptimizer()
        kelly, wr, payoff = opt.kelly_fraction("UNKNOWN_THING")
        assert wr == 0.50
        assert payoff == 1.5


class TestCompoundCurve:
    """Test equity-based tier system."""

    def test_bootstrap_tier(self):
        opt = SizingOptimizer()
        tier = opt.get_compound_tier(100.0)
        assert tier.label == "bootstrap"
        assert tier.kelly_fraction == 0.25
        assert tier.max_leverage == 25.0
        assert tier.max_positions == 2

    def test_growth_tier(self):
        opt = SizingOptimizer()
        tier = opt.get_compound_tier(350.0)
        assert tier.label == "growth"
        assert tier.kelly_fraction == 0.33

    def test_scaling_tier(self):
        opt = SizingOptimizer()
        tier = opt.get_compound_tier(750.0)
        assert tier.label == "scaling"

    def test_preservation_tier(self):
        opt = SizingOptimizer()
        tier = opt.get_compound_tier(7000.0)
        assert tier.label == "preservation"
        assert tier.max_leverage == 5.0  # Conservative at this size

    def test_wealth_tier(self):
        opt = SizingOptimizer()
        tier = opt.get_compound_tier(50000.0)
        assert tier.label == "wealth"

    def test_leverage_decreases_with_equity(self):
        """As equity grows, max leverage should decrease."""
        opt = SizingOptimizer()
        leverages = []
        for eq in [100, 300, 750, 2000, 7000]:
            tier = opt.get_compound_tier(eq)
            leverages.append(tier.max_leverage)
        # Should be monotonically non-increasing
        for i in range(len(leverages) - 1):
            assert leverages[i] >= leverages[i + 1]


class TestDynamicLeverage:
    """Test leverage calculation formula."""

    def test_high_wr_high_leverage(self):
        opt = SizingOptimizer()
        lev = opt.dynamic_leverage(
            win_rate=0.85, payoff=1.5, confidence=85.0,
            num_agree=3, regime="trend", is_dip_buy=True,
            tier_max_leverage=25.0,
        )
        assert lev >= 15.0  # High edge = high leverage

    def test_low_wr_low_leverage(self):
        opt = SizingOptimizer()
        lev = opt.dynamic_leverage(
            win_rate=0.50, payoff=1.0, confidence=60.0,
            num_agree=1, regime="consolidation", is_dip_buy=False,
            tier_max_leverage=25.0,
        )
        assert lev <= 5.0  # Marginal edge = low leverage

    def test_panic_regime_reduces_leverage(self):
        opt = SizingOptimizer()
        lev_trend = opt.dynamic_leverage(
            win_rate=0.71, payoff=1.5, confidence=80.0,
            num_agree=2, regime="trend", is_dip_buy=False,
            tier_max_leverage=25.0,
        )
        lev_panic = opt.dynamic_leverage(
            win_rate=0.71, payoff=1.5, confidence=80.0,
            num_agree=2, regime="panic", is_dip_buy=False,
            tier_max_leverage=25.0,
        )
        assert lev_panic < lev_trend

    def test_leverage_capped_by_tier(self):
        opt = SizingOptimizer()
        lev = opt.dynamic_leverage(
            win_rate=0.90, payoff=2.0, confidence=95.0,
            num_agree=3, regime="trending_bull", is_dip_buy=True,
            tier_max_leverage=5.0,  # Tier cap is low
        )
        assert lev <= 5.0

    def test_leverage_minimum_is_one(self):
        opt = SizingOptimizer()
        lev = opt.dynamic_leverage(
            win_rate=0.10, payoff=0.5, confidence=30.0,
            num_agree=1, regime="panic", is_dip_buy=False,
            tier_max_leverage=25.0,
        )
        assert lev >= 1.0


class TestGetOptimalSize:
    """Test the master sizing function."""

    def test_basic_sizing_100_equity(self):
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size(
            setup="HYPE_BUY", equity=100.0, confidence=82.0,
            num_agree=3, regime="consolidation", is_dip_buy=True,
            stop_width_pct=0.025,
        )
        assert sizing.risk_pct > 0.02
        assert sizing.risk_amount > 0
        assert sizing.leverage >= 1.0
        assert sizing.position_size_usd > 0
        assert sizing.margin_required <= 100.0 * 0.95
        assert sizing.compound_tier == "bootstrap"
        assert sizing.setup_wr == 0.52  # HYPE BUY prior (updated: edge weakening)

    def test_margin_never_exceeds_equity(self):
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size(
            setup="HYPE_BUY", equity=50.0, confidence=90.0,
            num_agree=3, stop_width_pct=0.005,  # Very tight stop
        )
        assert sizing.margin_required <= 50.0 * 0.95

    def test_max_loss_capped(self):
        """Single trade loss should never exceed max_single_loss_pct."""
        opt = SizingOptimizer(max_single_loss_pct=0.10)
        sizing = opt.get_optimal_size(
            setup="HYPE_BUY", equity=1000.0, confidence=90.0,
            num_agree=3, stop_width_pct=0.01,
        )
        assert sizing.risk_amount <= 1000.0 * 0.10 + 0.01  # Allow rounding

    def test_no_sizing_when_max_positions(self):
        """Should return zero risk when max positions reached."""
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size(
            setup="HYPE_BUY", equity=100.0,
            open_positions=2,  # bootstrap tier max = 2
        )
        assert sizing.risk_pct == opt.min_risk_pct or sizing.risk_amount < 5.0

    def test_losing_streak_reduces_size(self):
        """After losses, sizing should decrease."""
        opt = SizingOptimizer(min_trades_for_kelly=5)
        # Build up some history then lose
        for _ in range(5):
            opt.record_outcome("TEST", True, 3.0)
        base = opt.get_optimal_size("TEST", equity=100.0)

        for _ in range(3):
            opt.record_outcome("TEST", False, 2.0)
        after_losses = opt.get_optimal_size("TEST", equity=100.0)

        assert after_losses.risk_amount < base.risk_amount

    def test_win_streak_allows_increase(self):
        """After wins, sizing should increase."""
        opt = SizingOptimizer(min_trades_for_kelly=5)
        for _ in range(5):
            opt.record_outcome("STREAK", True, 3.0)
        opt.record_outcome("STREAK", False, 2.0)  # Reset streak
        base = opt.get_optimal_size("STREAK", equity=100.0)

        # Now win 3 more
        for _ in range(3):
            opt.record_outcome("STREAK", True, 3.0)
        after_wins = opt.get_optimal_size("STREAK", equity=100.0)

        assert after_wins.risk_amount >= base.risk_amount

    def test_different_equity_levels(self):
        """Higher equity should use lower leverage (preservation)."""
        opt = SizingOptimizer()
        small = opt.get_optimal_size("HYPE_BUY", equity=100.0)
        large = opt.get_optimal_size("HYPE_BUY", equity=10000.0)
        assert large.leverage <= small.leverage

    def test_rationale_is_populated(self):
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size("HYPE_BUY", equity=100.0)
        assert "Kelly" in sizing.rationale
        assert "WR" in sizing.rationale

    def test_toxic_setup_minimal_sizing(self):
        """HYPE SELL (7% WR) should get minimal sizing."""
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size("HYPE_SELL", equity=100.0)
        assert sizing.risk_pct == opt.min_risk_pct  # Clamped to minimum


class TestSetupStats:
    """Test the SetupStats data class."""

    def test_empty_stats(self):
        s = SetupStats()
        assert s.win_rate == 0.0
        assert s.avg_win == 0.0
        assert s.avg_loss == 0.0
        assert s.payoff_ratio == 2.0  # Default

    def test_win_rate(self):
        s = SetupStats(wins=7, losses=3)
        assert abs(s.win_rate - 0.7) < 0.01

    def test_payoff_ratio(self):
        s = SetupStats(wins=5, losses=5, total_win_pnl=25.0, total_loss_pnl=10.0)
        # avg_win = 5.0, avg_loss = 2.0, payoff = 2.5
        assert abs(s.payoff_ratio - 2.5) < 0.01
