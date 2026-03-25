"""Tests for portfolio-level risk budgeting."""
import pytest
from execution.portfolio_risk_budget import (
    PortfolioRiskBudget,
    get_correlation,
)


class TestBudgetAllocation:
    """Test budget allocation and limits."""

    def test_first_trade_always_allowed(self):
        budget = PortfolioRiskBudget()
        allowed, reason = budget.can_allocate("HYPE", "LONG", 10.0, 100.0)
        assert allowed

    def test_budget_limit_enforced(self):
        """Can't exceed daily budget."""
        budget = PortfolioRiskBudget(daily_budget_pct=0.20, max_direction_pct=0.90)  # 20% = $20, 90% direction
        budget.allocate("t1", "HYPE", "LONG", 12.0, 100.0)
        # $20 budget - $12 used = $8 available, but BTC needs $10 + correlation penalty
        allowed, reason = budget.can_allocate("BTC", "LONG", 10.0, 100.0)
        assert not allowed
        assert "Budget exceeded" in reason

    def test_direction_limit(self):
        """Can't put all budget in one direction."""
        budget = PortfolioRiskBudget(daily_budget_pct=0.50, max_direction_pct=0.60)
        # $50 budget, 60% direction = $30 max per direction
        budget.allocate("t1", "HYPE", "LONG", 25.0, 100.0)
        allowed, reason = budget.can_allocate("BTC", "LONG", 10.0, 100.0)
        assert not allowed
        assert "Long exposure" in reason

    def test_opposite_direction_allowed(self):
        """Can hedge with opposite direction."""
        budget = PortfolioRiskBudget(daily_budget_pct=0.50, max_direction_pct=0.60)
        budget.allocate("t1", "HYPE", "LONG", 25.0, 100.0)
        # Short should still be allowed (different direction)
        allowed, reason = budget.can_allocate("SOL", "SHORT", 10.0, 100.0)
        assert allowed

    def test_allocate_returns_allocation(self):
        budget = PortfolioRiskBudget()
        alloc = budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        assert alloc is not None
        assert alloc.symbol == "HYPE"
        assert alloc.risk_amount == 10.0

    def test_allocate_denied_returns_none(self):
        budget = PortfolioRiskBudget(daily_budget_pct=0.05)  # Tiny budget
        budget.allocate("t1", "HYPE", "LONG", 5.0, 100.0)
        alloc = budget.allocate("t2", "BTC", "LONG", 5.0, 100.0)
        assert alloc is None


class TestCorrelationPenalty:
    """Test correlation-adjusted budget consumption."""

    def test_correlated_trade_costs_more(self):
        """Adding a correlated position consumes extra budget."""
        budget = PortfolioRiskBudget(daily_budget_pct=0.50)
        # First trade: HYPE LONG
        alloc1 = budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        assert alloc1.correlation_penalty == 0.0  # No existing positions

        # Second trade: BTC LONG (correlated ~0.70)
        alloc2 = budget.allocate("t2", "BTC", "LONG", 10.0, 100.0)
        assert alloc2 is not None
        assert alloc2.correlation_penalty > 0  # Should have penalty

    def test_uncorrelated_no_penalty(self):
        """Opposite direction trades don't get correlation penalty."""
        budget = PortfolioRiskBudget()
        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        # Short is different direction — no correlation penalty
        alloc = budget.allocate("t2", "SOL", "SHORT", 10.0, 100.0)
        assert alloc is not None
        assert alloc.correlation_penalty == 0.0

    def test_known_correlations(self):
        assert get_correlation("BTC", "SOL") == 0.80
        assert get_correlation("BTC", "HYPE") == 0.70
        assert get_correlation("BTC", "BTC") == 1.0
        assert get_correlation("DOGE", "WIF") == 0.3  # Unknown = default


class TestDrawdownAdjustment:
    """Test budget reduction after losses."""

    def test_losses_reduce_budget(self):
        budget = PortfolioRiskBudget()
        initial = budget.get_daily_budget(100.0)

        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        budget.release("t1", won=False)
        budget.allocate("t2", "HYPE", "LONG", 10.0, 100.0)
        budget.release("t2", won=False)

        after_losses = budget.get_daily_budget(100.0)
        assert after_losses < initial

    def test_wins_recover_budget(self):
        budget = PortfolioRiskBudget()
        # Lose twice
        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        budget.release("t1", won=False)
        budget.allocate("t2", "HYPE", "LONG", 10.0, 100.0)
        budget.release("t2", won=False)
        after_losses = budget.get_daily_budget(100.0)

        # Win once
        budget.allocate("t3", "HYPE", "LONG", 10.0, 100.0)
        budget.release("t3", won=True)
        after_recovery = budget.get_daily_budget(100.0)

        assert after_recovery > after_losses

    def test_drawdown_floor(self):
        """Budget never drops below the floor."""
        budget = PortfolioRiskBudget(drawdown_floor=0.5)
        # Lose many times
        for i in range(10):
            budget.allocate(f"t{i}", "HYPE", "LONG", 5.0, 100.0)
            budget.release(f"t{i}", won=False)

        min_budget = 100.0 * budget.daily_budget_pct * 0.5
        assert budget.get_daily_budget(100.0) >= min_budget


class TestBudgetStatus:
    """Test status reporting."""

    def test_status_fields(self):
        budget = PortfolioRiskBudget()
        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        budget.allocate("t2", "SOL", "SHORT", 5.0, 100.0)

        status = budget.get_status(100.0)
        assert status.active_allocations == 2
        assert status.long_exposure == 10.0
        assert status.short_exposure == 5.0
        assert status.used > 0
        assert status.available >= 0

    def test_neutral_direction(self):
        budget = PortfolioRiskBudget()
        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        budget.allocate("t2", "SOL", "SHORT", 10.0, 100.0)
        status = budget.get_status(100.0)
        assert status.net_direction == "NEUTRAL"

    def test_long_biased(self):
        budget = PortfolioRiskBudget()
        budget.allocate("t1", "HYPE", "LONG", 20.0, 100.0)
        budget.allocate("t2", "SOL", "SHORT", 5.0, 100.0)
        status = budget.get_status(100.0)
        assert status.net_direction == "LONG"


class TestRelease:
    """Test budget release on trade close."""

    def test_release_frees_budget(self):
        budget = PortfolioRiskBudget()
        budget.allocate("t1", "HYPE", "LONG", 10.0, 100.0)
        assert budget.get_used_budget() > 0
        budget.release("t1", won=True)
        assert budget.get_used_budget() == 0

    def test_release_unknown_returns_none(self):
        budget = PortfolioRiskBudget()
        result = budget.release("nonexistent", won=True)
        assert result is None
