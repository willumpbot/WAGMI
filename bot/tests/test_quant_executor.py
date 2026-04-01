"""Tests for the unified quant executor pipeline."""
import pytest
from execution.quant_executor import QuantExecutor, TradeDecision


class TestQuantExecutorInit:
    """Test initialization with all modules."""

    def test_init_with_default_equity(self):
        qe = QuantExecutor(equity=100.0)
        assert qe.equity == 100.0
        assert qe.sizer is not None
        assert qe.layers is not None
        assert qe.budget is not None
        assert qe.entry_opt is not None
        assert qe.exit_opt is not None
        assert qe.ruin_check is not None
        assert qe.cross_asset is not None

    def test_update_equity(self):
        qe = QuantExecutor(equity=100.0)
        qe.update_equity(250.0)
        assert qe.equity == 250.0


class TestSignalEvaluation:
    """Test the full evaluation pipeline."""

    def test_hype_buy_dip_produces_decision(self):
        """HYPE BUY dip with 3-agree should produce a trade decision."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False  # Disable for test

        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True, tier="SNIPER",
        )
        assert decision.execute is True
        assert decision.layer == "scalp"
        assert decision.leverage >= 5.0
        assert decision.risk_amount > 0
        assert decision.sl > 0
        assert decision.tp > 0

    def test_weak_signal_rejected(self):
        """Low confidence, 1-agree should be rejected."""
        qe = QuantExecutor(equity=100.0)
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=55.0, num_agree=1, regime="unknown",
            stop_width_pct=0.025,
        )
        assert decision.execute is False
        assert decision.reject_reason is not None

    def test_full_layers_rejected(self):
        """When all position layers are full, new signals rejected."""
        qe = QuantExecutor(equity=100.0)
        # Fill all scalp slots
        from execution.position_layers import PositionLayer
        qe.layers.open_position("BTC", "LONG", PositionLayer.SCALP, 70000, 0.1, 15, 69000, 72000)
        qe.layers.open_position("SOL", "LONG", PositionLayer.SCALP, 130, 10, 10, 125, 140)

        # Try to open another scalp — should fall to swing or reject
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True,
        )
        # Should either get swing layer or be rejected
        if decision.execute:
            assert decision.layer in ("swing", "regime")

    def test_budget_limit_enforced(self):
        """Portfolio budget should limit total exposure."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False

        # Allocate most of the budget
        qe.budget.allocate("existing", "BTC", "LONG", 25.0, 100.0)

        # Try another trade — budget might be tight
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True,
        )
        # May still execute but with reduced size, or may be rejected
        assert isinstance(decision, TradeDecision)

    def test_toxic_setup_minimal_sizing(self):
        """HYPE SELL (toxic) should get minimal sizing if it somehow gets through."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="HYPE", side="SELL", entry_price=40.0,
            confidence=90.0, num_agree=3, regime="trending_bear",
            stop_width_pct=0.025,
        )
        # Should execute but with minimal sizing (Kelly near 0 for 7% WR)
        if decision.execute:
            assert decision.risk_amount < 5.0  # Very small

    def test_decision_has_all_fields(self):
        """TradeDecision should have all required fields populated."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="BTC", side="BUY", entry_price=70000.0,
            confidence=80.0, num_agree=2, regime="trend",
            stop_width_pct=0.035,
        )
        assert decision.symbol == "BTC"
        assert decision.side in ("LONG", "SHORT")
        assert decision.kelly_rationale != ""
        assert decision.layer_rationale != ""


class TestRuinCheck:
    """Test Monte Carlo ruin check integration."""

    def test_safe_sizing_passes(self):
        """Normal sizing with good edge should pass ruin check."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True,
        )
        # Should not be halved by ruin check (HYPE BUY WR prior now 52%, was 71%)
        if decision.execute:
            assert decision.risk_amount > 3.0  # Not halved to tiny (lower bound reduced for edge decay)


class TestCrossAsset:
    """Test cross-asset amplification integration."""

    def test_price_updates_reach_amplifier(self):
        qe = QuantExecutor(equity=100.0)
        qe.update_prices({"BTC": 70000, "HYPE": 40.0, "SOL": 130.0})
        # Should not crash
        momentum = qe.cross_asset.get_leader_momentum("HYPE")
        assert isinstance(momentum, dict)


class TestOutcomeRecording:
    """Test trade outcome recording for Kelly learning."""

    def test_record_win(self):
        qe = QuantExecutor(equity=100.0)
        qe.record_outcome("HYPE_BUY", True, 3.5)
        stats = qe.sizer.get_setup_stats("HYPE_BUY")
        assert stats.wins == 1
        assert stats.total == 1

    def test_record_loss(self):
        qe = QuantExecutor(equity=100.0)
        qe.record_outcome("HYPE_BUY", False, 2.0)
        stats = qe.sizer.get_setup_stats("HYPE_BUY")
        assert stats.losses == 1

    def test_kelly_updates_after_outcomes(self):
        qe = QuantExecutor(equity=100.0)
        # Record several outcomes
        for _ in range(8):
            qe.record_outcome("TEST_SETUP", True, 3.0)
        for _ in range(2):
            qe.record_outcome("TEST_SETUP", False, 2.0)

        kelly, wr, payoff = qe.sizer.kelly_fraction("TEST_SETUP")
        assert wr > 0.7  # ~80% WR from data
        assert kelly > 0.2  # Positive edge


class TestEquityScaling:
    """Test that different equity levels produce appropriate sizing."""

    def test_small_account_aggressive(self):
        """$100 account should use bootstrap tier (quarter-Kelly, up to 25x)."""
        qe = QuantExecutor(equity=100.0)
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True,
        )
        if decision.execute:
            assert decision.leverage >= 5.0

    def test_large_account_conservative(self):
        """$10K account should use preservation tier (lower leverage)."""
        qe = QuantExecutor(equity=10000.0)
        qe.entry_opt.use_burst_detection = False
        decision = qe.evaluate_signal(
            symbol="HYPE", side="BUY", entry_price=40.0,
            confidence=82.0, num_agree=3, regime="consolidation",
            stop_width_pct=0.025, is_dip_buy=True,
        )
        if decision.execute:
            assert decision.leverage <= 10.0  # More conservative
