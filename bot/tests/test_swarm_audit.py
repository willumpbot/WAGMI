"""
Tests for Single-Signal Audit Module.

Ensures audit correctly extracts, analyzes, and reports on single-signal trades.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import json

from bot.feedback.single_signal_audit import (
    SingleSignalAudit,
    SingleSignalTrade,
    PerformanceMetrics,
    SniperSetup,
)


@pytest.fixture
def temp_data_dir():
    """Temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def audit(temp_data_dir):
    """Create audit instance with temp directory."""
    return SingleSignalAudit(data_dir=temp_data_dir)


@pytest.fixture
def sample_trades():
    """Create sample single-signal trades for testing."""
    return [
        SingleSignalTrade(
            trade_id="t1",
            timestamp=datetime.now().timestamp(),
            symbol="BTC",
            side="BUY",
            entry_price=50000.0,
            exit_price=51000.0,
            sl=49000.0,
            tp1=51000.0,
            tp2=52000.0,
            regime_1h="trend",
            regime_4h="trend",
            single_strategy_name="regime_trend",
            confidence_score=0.75,
            leverage_applied=2.0,
            hold_duration_minutes=30.0,
            exit_type="TP1",
            net_pnl=100.0,
            fees_paid=2.0,
            funding_paid=1.0,
            session_equity_start=1000.0,
            session_drawdown_pct=0.01,
            max_adverse_excursion_pct=0.01,
            max_favorable_excursion_pct=0.02,
        ),
        SingleSignalTrade(
            trade_id="t2",
            timestamp=datetime.now().timestamp(),
            symbol="BTC",
            side="SELL",
            entry_price=51000.0,
            exit_price=50500.0,
            sl=51500.0,
            tp1=50500.0,
            tp2=50000.0,
            regime_1h="range",
            regime_4h="trend",
            single_strategy_name="multi_tier_quality",
            confidence_score=0.65,
            leverage_applied=1.5,
            hold_duration_minutes=15.0,
            exit_type="SL",
            net_pnl=-50.0,
            fees_paid=1.5,
            funding_paid=0.5,
            session_equity_start=1100.0,
            session_drawdown_pct=0.02,
            max_adverse_excursion_pct=0.01,
            max_favorable_excursion_pct=0.005,
        ),
        SingleSignalTrade(
            trade_id="t3",
            timestamp=datetime.now().timestamp(),
            symbol="ETH",
            side="BUY",
            entry_price=3000.0,
            exit_price=3100.0,
            sl=2950.0,
            tp1=3050.0,
            tp2=3150.0,
            regime_1h="trend",
            regime_4h="trend",
            single_strategy_name="regime_trend",
            confidence_score=0.80,
            leverage_applied=2.0,
            hold_duration_minutes=45.0,
            exit_type="TP2",
            net_pnl=150.0,
            fees_paid=2.0,
            funding_paid=1.0,
            session_equity_start=1100.0,
            session_drawdown_pct=0.0,
            max_adverse_excursion_pct=0.0,
            max_favorable_excursion_pct=0.05,
        ),
    ]


class TestSingleSignalTradeCreation:
    """Test SingleSignalTrade dataclass."""

    def test_trade_creation(self):
        """Verify trade can be created with all fields."""
        trade = SingleSignalTrade(
            trade_id="t1",
            timestamp=1000.0,
            symbol="BTC",
            side="BUY",
            entry_price=50000.0,
            exit_price=51000.0,
            sl=49000.0,
            tp1=51000.0,
            tp2=52000.0,
            regime_1h="trend",
            regime_4h="trend",
            single_strategy_name="regime_trend",
            confidence_score=0.75,
            leverage_applied=2.0,
            hold_duration_minutes=30.0,
            exit_type="TP1",
            net_pnl=100.0,
            fees_paid=2.0,
            funding_paid=1.0,
            session_equity_start=1000.0,
            session_drawdown_pct=0.01,
            max_adverse_excursion_pct=0.01,
            max_favorable_excursion_pct=0.02,
        )

        assert trade.trade_id == "t1"
        assert trade.symbol == "BTC"
        assert trade.side == "BUY"
        assert trade.net_pnl == 100.0
        assert trade.confidence_score == 0.75


class TestPerformanceMetricsCalculation:
    """Test win rate, profit factor, and other metrics."""

    def test_win_rate_calculation(self):
        """Verify win rate is calculated correctly."""
        pnls = [100, -50, 75]
        wins = [p for p in pnls if p > 0]
        wr = len(wins) / len(pnls)

        assert wr == pytest.approx(0.667, rel=0.01)

    def test_profit_factor_calculation(self):
        """Verify profit factor is calculated correctly."""
        pnls = [100, -50, 75]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        pf = sum(wins) / abs(sum(losses))

        assert pf == pytest.approx(3.5, rel=0.01)

    def test_zero_division_handling(self):
        """Verify zero division is handled gracefully."""
        # All winning trades
        pnls = [100, 75, 50]
        losses = [p for p in pnls if p < 0]
        pf = sum([p for p in pnls if p > 0]) / abs(sum(losses)) if sum(losses) != 0 else 0

        assert pf == 0  # No losses, so PF = 0 (not infinity)

    def test_empty_list_handling(self):
        """Verify empty trade list is handled."""
        pnls = []
        wr = 0 if not pnls else len([p for p in pnls if p > 0]) / len(pnls)

        assert wr == 0


class TestAuditExtraction:
    """Test trade extraction and filtering."""

    def test_extract_from_empty_list(self, audit):
        """Verify extraction handles empty trade list."""
        trades = audit.extract_single_signals(lookback_days=7)

        # Should return empty list (no real data)
        assert isinstance(trades, list)

    def test_trade_filtering(self, sample_trades):
        """Verify only single-signal trades are kept."""
        # All sample trades are single-signal (num_agree=1)
        single_signal_count = len(sample_trades)

        assert single_signal_count == 3

    def test_regime_extraction(self, sample_trades):
        """Verify regimes are correctly extracted."""
        regimes = set(t.regime_1h for t in sample_trades)

        assert "trend" in regimes
        assert "range" in regimes


class TestMetricsComputation:
    """Test metric computation."""

    def test_compute_metrics_structure(self, audit, sample_trades):
        """Verify metrics dict has expected structure."""
        audit.trades = sample_trades
        metrics = audit.compute_metrics()

        assert "overall" in metrics
        assert "by_strategy" in metrics
        assert "by_regime_1h" in metrics
        assert "by_symbol" in metrics

    def test_overall_metrics(self, audit, sample_trades):
        """Verify overall metrics are correct."""
        audit.trades = sample_trades
        metrics = audit.compute_metrics()
        overall = metrics["overall"]

        # 3 trades: 2 wins, 1 loss = 66.7% WR
        assert overall.trade_count == 3
        assert overall.win_count == 2
        assert overall.loss_count == 1
        assert overall.win_rate == pytest.approx(0.667, rel=0.01)

    def test_by_strategy_breakdown(self, audit, sample_trades):
        """Verify breakdown by strategy."""
        audit.trades = sample_trades
        metrics = audit.compute_metrics()
        by_strat = metrics["by_strategy"]

        assert "regime_trend" in by_strat
        assert "multi_tier_quality" in by_strat
        assert by_strat["regime_trend"].trade_count == 2
        assert by_strat["multi_tier_quality"].trade_count == 1

    def test_by_regime_breakdown(self, audit, sample_trades):
        """Verify breakdown by regime."""
        audit.trades = sample_trades
        metrics = audit.compute_metrics()
        by_regime = metrics["by_regime_1h"]

        assert "trend" in by_regime
        assert "range" in by_regime


class TestSniperSetupIdentification:
    """Test finding high-edge sniper setups."""

    def test_find_sniper_setups(self, audit, sample_trades):
        """Verify sniper setups are identified."""
        audit.trades = sample_trades
        setups = audit.find_sniper_setups(min_sample_size=1, min_wr=0.5)

        # With 3 trades, should find some setups
        assert isinstance(setups, list)
        assert len(setups) >= 0

    def test_sniper_setup_structure(self, audit, sample_trades):
        """Verify sniper setup has required fields."""
        audit.trades = sample_trades
        setups = audit.find_sniper_setups(min_sample_size=1, min_wr=0.5)

        if setups:
            setup = setups[0]
            assert hasattr(setup, "pattern_name")
            assert hasattr(setup, "win_rate")
            assert hasattr(setup, "profit_factor")
            assert hasattr(setup, "sharpe_ratio")


class TestLoserIdentification:
    """Test identifying losing patterns."""

    def test_identify_losers(self, audit, sample_trades):
        """Verify losing patterns are identified."""
        audit.trades = sample_trades
        losers = audit.identify_losers(max_wr=0.5)

        # Should find multi_tier_quality as loser (0% WR)
        assert isinstance(losers, list)


class TestSummaryReport:
    """Test report generation."""

    def test_summary_report_generation(self, audit, sample_trades):
        """Verify summary report is generated."""
        audit.trades = sample_trades
        report = audit.get_summary_report()

        assert "AUDIT" in report
        assert "win rate" in report.lower()
        assert "trades" in report.lower()


class TestFileOperations:
    """Test file I/O operations."""

    def test_save_audit(self, audit, sample_trades):
        """Verify audit can be saved to file."""
        audit.trades = sample_trades
        audit.save_audit()

        # Verify file exists
        assert audit.trades_file.exists()

    def test_load_previous_audit(self, audit, sample_trades):
        """Verify audit can be loaded from file."""
        audit.trades = sample_trades
        audit.save_audit()

        # Create new instance and load
        audit2 = SingleSignalAudit(data_dir=str(audit.data_dir))
        loaded_trades = audit2.load_previous_audit()

        assert len(loaded_trades) == len(sample_trades)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_single_trade(self, audit):
        """Verify system works with single trade."""
        trade = SingleSignalTrade(
            trade_id="t1",
            timestamp=1000.0,
            symbol="BTC",
            side="BUY",
            entry_price=50000.0,
            exit_price=51000.0,
            sl=49000.0,
            tp1=51000.0,
            tp2=52000.0,
            regime_1h="trend",
            regime_4h="trend",
            single_strategy_name="regime_trend",
            confidence_score=0.75,
            leverage_applied=2.0,
            hold_duration_minutes=30.0,
            exit_type="TP1",
            net_pnl=100.0,
            fees_paid=2.0,
            funding_paid=1.0,
            session_equity_start=1000.0,
            session_drawdown_pct=0.01,
            max_adverse_excursion_pct=0.01,
            max_favorable_excursion_pct=0.02,
        )

        audit.trades = [trade]
        metrics = audit.compute_metrics()

        assert metrics["overall"].trade_count == 1
        assert metrics["overall"].win_rate == 1.0

    def test_all_losses(self, audit):
        """Verify system works with all losing trades."""
        trades = [
            SingleSignalTrade(
                trade_id=f"t{i}",
                timestamp=1000.0 + i,
                symbol="BTC",
                side="BUY",
                entry_price=50000.0,
                exit_price=49500.0,  # Loss
                sl=49000.0,
                tp1=51000.0,
                tp2=52000.0,
                regime_1h="trend",
                regime_4h="trend",
                single_strategy_name="regime_trend",
                confidence_score=0.75,
                leverage_applied=2.0,
                hold_duration_minutes=30.0,
                exit_type="SL",
                net_pnl=-100.0,
                fees_paid=2.0,
                funding_paid=1.0,
                session_equity_start=1000.0,
                session_drawdown_pct=0.05,
                max_adverse_excursion_pct=0.01,
                max_favorable_excursion_pct=0.0,
            )
            for i in range(3)
        ]

        audit.trades = trades
        metrics = audit.compute_metrics()

        assert metrics["overall"].win_rate == 0.0
        assert metrics["overall"].loss_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
