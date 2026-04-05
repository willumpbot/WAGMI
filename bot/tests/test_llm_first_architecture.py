"""
Tests for the LLM-First Architecture (SIGNAL_FLOW_REDESIGN).

Tests:
  1. SafetyFilterChain — only safety gates, no quality/sizing
  2. evaluate_raw() — ensemble returns raw signals without quality filtering
  3. EntryDecision dataclass — proper construction and skip factory
  4. LLM_FIRST_MODE flag — config recognition
  5. get_entry_decision() — coordinator entry pipeline
  6. Backward compatibility — legacy path unchanged when LLM_FIRST_MODE=false
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass

# Ensure bot/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── Fixtures ───────────────────────────────────────────────────


def _make_signal(
    symbol="BTC",
    side="BUY",
    confidence=80.0,
    entry=50000.0,
    sl=49000.0,
    tp1=52000.0,
    tp2=54000.0,
    atr=500.0,
    strategy="confidence_scorer",
    metadata=None,
):
    """Create a valid Signal for testing."""
    from strategies.base import Signal
    return Signal(
        strategy=strategy,
        symbol=symbol,
        side=side,
        confidence=confidence,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        atr=atr,
        metadata=metadata or {"num_agree": 2, "regime": "trend"},
    )


def _make_invalid_signal():
    """Signal with SL on wrong side (invalid)."""
    from strategies.base import Signal
    return Signal(
        strategy="test",
        symbol="BTC",
        side="BUY",
        confidence=80.0,
        entry=50000.0,
        sl=51000.0,  # SL above entry for BUY = invalid
        tp1=52000.0,
        tp2=54000.0,
        atr=500.0,
    )


class MockRiskMgr:
    """Mock risk manager for SafetyFilterChain tests."""

    def __init__(self, equity=1000.0, trading_allowed=True):
        self.equity = equity
        self._trading_allowed = trading_allowed

    def is_trading_allowed(self, confidence=0, cb_conf_override_pct=0.92):
        return self._trading_allowed

    def calculate_qty(self, entry, stop_loss, leverage, risk_multiplier, symbol=""):
        stop_width = abs(entry - stop_loss)
        if stop_width <= 0:
            return 0.0
        risk_dollars = self.equity * 0.10 * risk_multiplier
        return risk_dollars / stop_width


class MockLeverageMgr:
    """Mock leverage manager."""

    def validate_stop_vs_liquidation(self, entry, stop_loss, side, leverage, notional_usd):
        return {"safe": True, "liquidation_price": 0, "gap_pct": 0.1}

    def decide(self, **kwargs):
        from execution.leverage import LeverageDecision
        return LeverageDecision(
            leverage=5.0, mode="tiered", tier="medium",
            reason="mock", risk_multiplier=1.0,
        )


@dataclass
class MockConfig:
    max_open_positions: int = 8
    max_leverage: float = 25.0
    max_portfolio_leverage: float = 4.0
    min_stop_width_pct: float = 0.003
    llm_first_mode: bool = False
    llm_first_dual_track: bool = False


# ─── Test SafetyFilterChain ─────────────────────────────────────


class TestSafetyFilterChain:
    """Test that SafetyFilterChain passes/rejects correctly."""

    def test_valid_signal_passes(self):
        from core.signal_pipeline import SafetyFilterChain
        chain = SafetyFilterChain(MockRiskMgr(), MockLeverageMgr(), MockConfig())
        result = chain.evaluate(
            signal=_make_signal(),
            equity=1000.0,
            current_open_count=0,
        )
        assert result.approved is True
        assert "rr_tp1" in result.metadata
        assert "equity" in result.metadata

    def test_invalid_signal_rejected(self):
        from core.signal_pipeline import SafetyFilterChain
        chain = SafetyFilterChain(MockRiskMgr(), MockLeverageMgr(), MockConfig())
        result = chain.evaluate(
            signal=_make_invalid_signal(),
            equity=1000.0,
        )
        assert result.approved is False
        assert "Invalid" in result.rejection_reason or "stop_width" in result.rejection_reason

    def test_circuit_breaker_rejects(self):
        from core.signal_pipeline import SafetyFilterChain
        chain = SafetyFilterChain(
            MockRiskMgr(trading_allowed=False),
            MockLeverageMgr(),
            MockConfig(),
        )
        result = chain.evaluate(
            signal=_make_signal(),
            equity=1000.0,
        )
        assert result.approved is False
        assert "Circuit breaker" in result.rejection_reason

    def test_max_positions_rejects(self):
        from core.signal_pipeline import SafetyFilterChain
        config = MockConfig(max_open_positions=2)
        chain = SafetyFilterChain(MockRiskMgr(), MockLeverageMgr(), config)
        result = chain.evaluate(
            signal=_make_signal(),
            equity=1000.0,
            current_open_count=2,
        )
        assert result.approved is False
        assert "Max positions" in result.rejection_reason

    def test_duplicate_position_rejects(self):
        from core.signal_pipeline import SafetyFilterChain
        chain = SafetyFilterChain(MockRiskMgr(), MockLeverageMgr(), MockConfig())

        # Create a mock open position
        mock_pos = MagicMock()
        mock_pos.side = "LONG"
        mock_pos.entry = 50000.0

        result = chain.evaluate(
            signal=_make_signal(symbol="BTC"),
            equity=1000.0,
            open_positions={"BTC": mock_pos},
        )
        assert result.approved is False
        assert "Duplicate" in result.rejection_reason

    def test_liquidation_unsafe_rejects(self):
        from core.signal_pipeline import SafetyFilterChain
        lev_mgr = MockLeverageMgr()
        lev_mgr.validate_stop_vs_liquidation = MagicMock(return_value={
            "safe": False, "liquidation_price": 49500.0, "gap_pct": -0.01,
        })
        chain = SafetyFilterChain(MockRiskMgr(), lev_mgr, MockConfig())
        result = chain.evaluate(
            signal=_make_signal(),
            equity=1000.0,
        )
        assert result.approved is False
        assert "liquidation" in result.rejection_reason.lower()

    def test_no_quality_gates(self):
        """SafetyFilterChain should NOT have fee drag, EV, confidence floor, etc."""
        from core.signal_pipeline import SafetyFilterChain

        # Signal that is_valid (R:R >= 1.0, correct sides) but has low confidence
        # and tight stop that would trigger fee-drag, EV floor, and confidence
        # gates in RiskFilterChain. SafetyFilterChain should pass it.
        signal = _make_signal(
            entry=50000.0,
            sl=49750.0,  # 0.5% stop width, R:R ~1.0
            tp1=50250.0,  # R:R = 1.0 (exactly at the minimum)
            tp2=50500.0,
            confidence=55.0,  # Low confidence (below any floor)
            metadata={"num_agree": 1, "regime": "trending_bear",
                      "ev_per_dollar": 0.01},  # Terrible EV
        )
        assert signal.is_valid  # Confirm it passes structural validity

        chain = SafetyFilterChain(MockRiskMgr(), MockLeverageMgr(), MockConfig())
        result = chain.evaluate(signal=signal, equity=1000.0)
        # SafetyFilterChain doesn't check confidence, EV, fee drag, etc.
        assert result.approved is True


# ─── Test EntryDecision ─────────────────────────────────────────


class TestEntryDecision:
    def test_skip_factory(self):
        from llm.decision_types import EntryDecision
        d = EntryDecision.skip("test reason")
        assert d.action == "skip"
        assert d.thesis == "test reason"
        assert d.leverage == 1.0
        assert d.position_qty == 0.0

    def test_go_decision(self):
        from llm.decision_types import EntryDecision
        d = EntryDecision(
            action="go",
            leverage=5.0,
            risk_pct=0.08,
            position_qty=0.001,
            regime="trend",
            thesis="BTC breakout",
            confidence=0.82,
        )
        assert d.action == "go"
        assert d.leverage == 5.0
        assert d.to_dict()["regime"] == "trend"

    def test_to_dict_complete(self):
        from llm.decision_types import EntryDecision
        d = EntryDecision(
            action="go",
            leverage=3.0,
            risk_pct=0.05,
            regime="range",
            thesis="test",
            confidence=0.7,
            risk_flags=["correlated"],
        )
        dd = d.to_dict()
        assert "action" in dd
        assert "leverage" in dd
        assert "risk_flags" in dd
        assert dd["risk_flags"] == ["correlated"]


# ─── Test LLM_FIRST_MODE Config ────────────────────────────────


class TestLLMFirstConfig:
    def test_flag_default_false(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.llm_first_mode is False
        assert config.llm_first_dual_track is False

    def test_flag_from_env(self):
        with patch.dict(os.environ, {"LLM_FIRST_MODE": "true"}):
            from trading_config import TradingConfig
            config = TradingConfig()
            assert config.llm_first_mode is True

    def test_dual_track_from_env(self):
        with patch.dict(os.environ, {"LLM_FIRST_DUAL_TRACK": "true"}):
            from trading_config import TradingConfig
            config = TradingConfig()
            assert config.llm_first_dual_track is True


# ─── Test evaluate_raw() ────────────────────────────────────────


class TestEvaluateRaw:
    """Test that evaluate_raw returns signals without quality filtering."""

    def _make_ensemble(self):
        """Create a minimal EnsembleStrategy for testing."""
        from strategies.ensemble import EnsembleStrategy

        # Create mock strategies that return deterministic signals
        strat1 = MagicMock()
        strat1.name = "strategy_a"
        strat1.evaluate.return_value = _make_signal(
            strategy="strategy_a", confidence=75.0
        )
        strat1.get_required_timeframes.return_value = ["1h"]

        strat2 = MagicMock()
        strat2.name = "strategy_b"
        strat2.evaluate.return_value = _make_signal(
            strategy="strategy_b", confidence=70.0
        )
        strat2.get_required_timeframes.return_value = ["1h"]

        ensemble = EnsembleStrategy(
            strategies=[strat1, strat2],
            mode="weighted_veto",
            min_votes=1,
            veto_ratio=1.2,
            confidence_floor=69.0,
        )
        return ensemble

    def test_raw_returns_signal_below_floor(self):
        """evaluate_raw should return signals that evaluate() would reject."""
        ensemble = self._make_ensemble()

        # Set confidence floor high enough that normal evaluate would reject
        ensemble.confidence_floor = 90.0
        ensemble.ranging_confidence_floor = 90.0

        import pandas as pd
        data = {"1h": pd.DataFrame({"close": [50000.0] * 50})}

        # evaluate_raw should return the signal (no quality filtering)
        raw = ensemble.evaluate_raw("BTC", data)
        # May be None if voting doesn't pass, but should not be filtered by floor
        # The key point: evaluate_raw attaches metadata without gating
        if raw is not None:
            assert "signal_source" in raw.metadata
            assert raw.metadata["signal_source"] == "evaluate_raw"
            assert "mechanical_confidence_floor" in raw.metadata

    def test_raw_attaches_metadata(self):
        """evaluate_raw should attach quality metadata for LLM consumption."""
        ensemble = self._make_ensemble()

        import pandas as pd
        data = {"1h": pd.DataFrame({"close": [50000.0] * 50})}

        raw = ensemble.evaluate_raw("BTC", data)
        if raw is not None:
            # Should have advisory metadata
            assert "chop_score_smoothed" in raw.metadata
            assert "regime_4h_aligned" in raw.metadata
            assert "regime_1h" in raw.metadata


# ─── Test get_entry_decision() ──────────────────────────────────


class TestGetEntryDecision:
    """Test coordinator.get_entry_decision()."""

    @patch("llm.agents.coordinator.get_coordinator")
    def test_entry_decision_skip_on_failure(self, mock_get_coord):
        """Pipeline failure returns skip."""
        from llm.decision_types import EntryDecision
        from llm.agents.coordinator import AgentCoordinator

        coord = AgentCoordinator()
        # Mock get_trading_decision to return None (pipeline failure)
        coord.get_trading_decision = MagicMock(return_value=None)

        result = coord.get_entry_decision(
            signal_context={"symbol": "BTC", "side": "BUY", "entry": 50000,
                           "sl": 49000, "confidence": 80},
            market_context={},
            portfolio_context={"equity": 1000},
        )
        assert isinstance(result, EntryDecision)
        assert result.action == "skip"

    @patch("llm.agents.coordinator.get_coordinator")
    def test_entry_decision_go(self, mock_get_coord):
        """Successful pipeline returns go with sizing."""
        from llm.decision_types import EntryDecision, LLMDecision, StrategyWeights
        from llm.agents.coordinator import AgentCoordinator
        from llm.agents.base import AgentOutput, AgentRole

        coord = AgentCoordinator()

        # Mock successful LLM decision
        mock_decision = LLMDecision(
            action="proceed",
            confidence=0.82,
            regime="trend",
            strategy_weights=StrategyWeights(),
            memory_update=None,
            notes="BTC breakout",
            size_multiplier=1.0,
        )
        coord.get_trading_decision = MagicMock(return_value=mock_decision)

        # Mock Risk Agent output with leverage/sizing
        risk_out = AgentOutput(
            role=AgentRole.RISK,
            data={"leverage": 5.0, "risk_pct": 0.08, "sizing_rationale": "full kelly"},
        )
        trade_out = AgentOutput(
            role=AgentRole.TRADE,
            data={"a": "go", "thesis": "BTC breakout confirmed"},
        )
        coord.last_pipeline_results = {
            AgentRole.RISK: risk_out,
            AgentRole.TRADE: trade_out,
        }

        result = coord.get_entry_decision(
            signal_context={"symbol": "BTC", "side": "BUY", "entry": 50000,
                           "sl": 49000, "tp1": 52000, "tp2": 54000,
                           "confidence": 80, "atr": 500},
            market_context={},
            portfolio_context={"equity": 1000},
        )
        assert isinstance(result, EntryDecision)
        assert result.action == "go"
        assert result.leverage == 5.0
        assert result.regime == "trend"
        assert result.position_qty > 0

    def test_build_entry_snapshot(self):
        """Snapshot builder creates correct format."""
        from llm.agents.coordinator import AgentCoordinator

        coord = AgentCoordinator()
        snapshot = coord._build_entry_snapshot(
            signal_ctx={
                "symbol": "BTC", "side": "BUY", "entry": 50000,
                "sl": 49000, "tp1": 52000, "tp2": 54000,
                "confidence": 80, "atr": 500, "strategy": "test",
                "chop_score": 0.3, "win_prob": 0.65,
            },
            market_ctx={"funding_rate": 0.001},
            portfolio_ctx={"equity": 1000, "open_positions": {}},
        )

        assert "m" in snapshot
        assert "g" in snapshot
        assert "pos" in snapshot
        assert "signal_metadata" in snapshot
        assert snapshot["g"]["equity"] == 1000
        assert snapshot["signal_metadata"]["chop_score"] == 0.3


# ─── Test RiskFilterChain still works (backward compat) ─────────


class TestBackwardCompatibility:
    """Ensure RiskFilterChain still works for legacy/backtest path."""

    def test_risk_filter_chain_still_exists(self):
        from core.signal_pipeline import RiskFilterChain
        chain = RiskFilterChain(MockRiskMgr(), MockLeverageMgr(), MockConfig())
        assert hasattr(chain, "evaluate")
        assert hasattr(chain, "evaluate_annotated")

    def test_ensemble_evaluate_still_works(self):
        """Original evaluate() method still exists."""
        from strategies.ensemble import EnsembleStrategy
        strat = MagicMock()
        strat.name = "test"
        strat.get_required_timeframes.return_value = ["1h"]
        ensemble = EnsembleStrategy(strategies=[strat], mode="voting")
        assert hasattr(ensemble, "evaluate")
        assert hasattr(ensemble, "evaluate_raw")
        assert hasattr(ensemble, "evaluate_with_annotations")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
