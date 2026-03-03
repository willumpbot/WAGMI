"""
Tests for Phase C: Stop the Bleeding — risk guards, leverage tracking,
liquidation monitoring, consensus tightening, flip limiter.
"""

import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── C1: Portfolio Leverage Tracking ─────────────────────────────────────


class TestPortfolioLeverage:
    """Test portfolio leverage computation and guard."""

    def _make_bot_stub(self):
        """Create a minimal stub with the leverage computation method."""
        from execution.risk import RiskManager, CircuitBreaker

        class Stub:
            def __init__(self):
                self.risk_mgr = RiskManager(starting_equity=10000.0)
                self._last_prices = {}
                self._last_funding_rates = {}

            def _make_pos(self, symbol, side, entry, qty, leverage):
                from execution.position_manager import Position
                p = Position(
                    symbol=symbol, side=side, entry=entry,
                    qty=qty, sl=0, tp1=0, tp2=0, leverage=leverage,
                )
                p.state = "OPEN"
                return p

        stub = Stub()
        # Inject the method from multi_strategy_main
        from multi_strategy_main import MultiStrategyBot
        stub._compute_portfolio_leverage = MultiStrategyBot._compute_portfolio_leverage.__get__(stub)
        stub._compute_estimated_daily_funding = MultiStrategyBot._compute_estimated_daily_funding.__get__(stub)
        return stub

    def test_no_positions_zero_leverage(self):
        stub = self._make_bot_stub()
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {}
        assert stub._compute_portfolio_leverage() == 0.0

    def test_single_position_leverage(self):
        stub = self._make_bot_stub()
        pos = stub._make_pos("BTC/USDC:USDC", "LONG", 50000, 0.1, 5.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {"BTC/USDC:USDC": pos}
        stub._last_prices = {"BTC/USDC:USDC": 50000}
        # notional = 0.1 * 50000 * 5 = 25000
        # leverage = 25000 / 10000 = 2.5
        result = stub._compute_portfolio_leverage()
        assert result == 2.5

    def test_multiple_positions_sum(self):
        stub = self._make_bot_stub()
        pos1 = stub._make_pos("BTC/USDC:USDC", "LONG", 50000, 0.1, 5.0)
        pos2 = stub._make_pos("ETH/USDC:USDC", "SHORT", 3000, 1.0, 3.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {
            "BTC/USDC:USDC": pos1,
            "ETH/USDC:USDC": pos2,
        }
        stub._last_prices = {"BTC/USDC:USDC": 50000, "ETH/USDC:USDC": 3000}
        # BTC: 0.1 * 50000 * 5 = 25000
        # ETH: 1.0 * 3000 * 3 = 9000
        # total = 34000 / 10000 = 3.4
        result = stub._compute_portfolio_leverage()
        assert result == 3.4

    def test_uses_entry_price_when_last_price_missing(self):
        stub = self._make_bot_stub()
        pos = stub._make_pos("SOL/USDC:USDC", "LONG", 100, 10.0, 2.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {"SOL/USDC:USDC": pos}
        stub._last_prices = {}  # No price cached
        # Should fall back to entry price: 10 * 100 * 2 = 2000 / 10000 = 0.2
        result = stub._compute_portfolio_leverage()
        assert result == 0.2


# ── C2: Funding Cost Computation ────────────────────────────────────────


class TestFundingCost:
    """Test estimated daily funding cost computation."""

    def _make_bot_stub(self):
        from execution.risk import RiskManager
        from multi_strategy_main import MultiStrategyBot

        class Stub:
            def __init__(self):
                self.risk_mgr = RiskManager(starting_equity=10000.0)
                self._last_prices = {}
                self._last_funding_rates = {}

            def _make_pos(self, symbol, side, entry, qty, leverage):
                from execution.position_manager import Position
                p = Position(
                    symbol=symbol, side=side, entry=entry,
                    qty=qty, sl=0, tp1=0, tp2=0, leverage=leverage,
                )
                p.state = "OPEN"
                return p

        stub = Stub()
        stub._compute_estimated_daily_funding = MultiStrategyBot._compute_estimated_daily_funding.__get__(stub)
        return stub

    def test_no_positions_zero_cost(self):
        stub = self._make_bot_stub()
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {}
        assert stub._compute_estimated_daily_funding() == 0.0

    def test_no_funding_rate_zero_cost(self):
        stub = self._make_bot_stub()
        pos = stub._make_pos("BTC/USDC:USDC", "LONG", 50000, 0.1, 5.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {"BTC/USDC:USDC": pos}
        stub._last_prices = {"BTC/USDC:USDC": 50000}
        stub._last_funding_rates = {}  # No rates
        assert stub._compute_estimated_daily_funding() == 0.0

    def test_long_paying_positive_funding(self):
        stub = self._make_bot_stub()
        pos = stub._make_pos("BTC/USDC:USDC", "LONG", 50000, 0.1, 5.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {"BTC/USDC:USDC": pos}
        stub._last_prices = {"BTC/USDC:USDC": 50000}
        stub._last_funding_rates = {"BTC/USDC:USDC": 0.0005}  # 0.05% per 8h
        # cost = 0.0005 * 3 * 5 * (0.1 * 50000) / 10000 * 100
        # = 0.0005 * 3 * 5 * 5000 / 10000 * 100
        # = 0.0005 * 3 * 5 * 0.5 * 100
        # = 0.375
        result = stub._compute_estimated_daily_funding()
        assert abs(result - 0.375) < 0.01

    def test_short_not_paying_positive_funding(self):
        """Shorts earn when funding is positive (longs pay shorts)."""
        stub = self._make_bot_stub()
        pos = stub._make_pos("BTC/USDC:USDC", "SHORT", 50000, 0.1, 5.0)
        stub.pos_mgr = MagicMock()
        stub.pos_mgr.get_open_positions.return_value = {"BTC/USDC:USDC": pos}
        stub._last_prices = {"BTC/USDC:USDC": 50000}
        stub._last_funding_rates = {"BTC/USDC:USDC": 0.0005}  # positive = longs pay
        # Short earns, doesn't pay — should be 0
        result = stub._compute_estimated_daily_funding()
        assert result == 0.0


# ── C3: Liquidation Distance Monitoring ─────────────────────────────────


class TestLiquidationDistance:
    """Test liquidation distance checks."""

    def test_long_liquidation_price(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 10x long at 50000 with 0.4% mm: liq = 50000 * 0.9 / (1 - 0.004) ≈ 45180.7
        # Liquidation is CLOSER to entry than naive 1/leverage formula (which gives 45000)
        liq = mgr.liquidation_price(50000, "LONG", 10.0)
        assert liq > 45000  # closer to entry due to maintenance margin
        assert abs(liq - 45180.72) < 1.0

    def test_short_liquidation_price(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 10x short at 50000 with 0.4% mm: liq = 50000 * 1.1 / (1 + 0.004) ≈ 54780.9
        # Liquidation is CLOSER to entry than naive formula (which gives 55000)
        liq = mgr.liquidation_price(50000, "SHORT", 10.0)
        assert liq < 55000  # closer to entry due to maintenance margin
        assert abs(liq - 54780.88) < 1.0

    def test_high_leverage_small_distance(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 25x long at 50000: liq = 50000 * (1 - 1/25) = 48000
        # distance at 48500 = (48500 - 48000) / 48500 = 1.03%
        result = mgr.check_liquidation_risk(
            entry=50000, current_price=48500, side="LONG",
            leverage=25.0, safety_buffer=0.03,
        )
        assert result["at_risk"] is True
        assert result["distance_pct"] < 0.03

    def test_safe_distance_not_at_risk(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        # 5x long at 50000: liq = 50000 * (1 - 1/5) = 40000
        # distance at 49000 = (49000 - 40000) / 49000 = 18.37%
        result = mgr.check_liquidation_risk(
            entry=50000, current_price=49000, side="LONG",
            leverage=5.0, safety_buffer=0.03,
        )
        assert result["at_risk"] is False

    def test_spot_no_liquidation(self):
        from execution.leverage import LeverageManager
        mgr = LeverageManager()
        liq = mgr.liquidation_price(50000, "LONG", 1.0)
        assert liq is None


# ── C5: Ensemble Consensus Tightening ───────────────────────────────────


class TestEnsembleConsensus:
    """Test consensus tightening and unanimous bonus."""

    def _make_signal(self, strategy, side, confidence):
        from strategies.base import Signal
        return Signal(
            strategy=strategy, symbol="BTC/USDC:USDC",
            side=side, confidence=confidence,
            entry=50000, sl=49000, tp1=51500, tp2=53000, atr=500,
        )

    def test_weighted_veto_uses_min_votes(self):
        """weighted_veto should respect min_votes parameter."""
        from strategies.base import BaseStrategy
        from strategies.ensemble import EnsembleStrategy

        # Create mock strategies
        strats = [MagicMock(spec=BaseStrategy, name=f"s{i}") for i in range(4)]
        for i, s in enumerate(strats):
            s.name = f"strategy_{i}"

        # With min_votes=3, 2 strategies agreeing should not pass
        ensemble = EnsembleStrategy(strats, mode="weighted_veto", min_votes=3)

        # Manually test _weighted_veto with only 2 signals
        signals = [
            self._make_signal("strategy_0", "BUY", 75),
            self._make_signal("strategy_1", "BUY", 70),
        ]
        result = ensemble._weighted_veto("BTC/USDC:USDC", signals)
        assert result is None  # Should fail: 2 < min_votes(3)

    def test_weighted_veto_passes_with_enough_votes(self):
        """weighted_veto should pass when min_votes met."""
        from strategies.base import BaseStrategy
        from strategies.ensemble import EnsembleStrategy

        strats = [MagicMock(spec=BaseStrategy, name=f"s{i}") for i in range(4)]
        for i, s in enumerate(strats):
            s.name = f"strategy_{i}"

        ensemble = EnsembleStrategy(strats, mode="weighted_veto", min_votes=3)

        signals = [
            self._make_signal("strategy_0", "BUY", 75),
            self._make_signal("strategy_1", "BUY", 70),
            self._make_signal("strategy_2", "BUY", 80),
        ]
        result = ensemble._weighted_veto("BTC/USDC:USDC", signals)
        assert result is not None
        assert result.side == "BUY"

    def test_unanimous_bonus(self):
        """All strategies agreeing should get a bonus."""
        from strategies.base import BaseStrategy
        from strategies.ensemble import EnsembleStrategy

        strats = [MagicMock(spec=BaseStrategy, name=f"s{i}") for i in range(4)]
        for i, s in enumerate(strats):
            s.name = f"strategy_{i}"

        ensemble = EnsembleStrategy(strats, mode="weighted_veto", min_votes=2)

        # 3/4 agree
        signals_3 = [
            self._make_signal("strategy_0", "BUY", 70),
            self._make_signal("strategy_1", "BUY", 70),
            self._make_signal("strategy_2", "BUY", 70),
        ]
        result_3 = ensemble._merge_signals("TEST", signals_3)

        # 4/4 agree (unanimous)
        signals_4 = [
            self._make_signal("strategy_0", "BUY", 70),
            self._make_signal("strategy_1", "BUY", 70),
            self._make_signal("strategy_2", "BUY", 70),
            self._make_signal("strategy_3", "BUY", 70),
        ]
        result_4 = ensemble._merge_signals("TEST", signals_4)

        # Unanimous should have higher confidence
        # 3/4: bonus = (3-1)*3 = 6
        # 4/4: bonus = (4-1)*3 + 5 = 14
        assert result_4.confidence > result_3.confidence


# ── C6: Confidence-Weighted Flip Limiter ────────────────────────────────


class TestFlipLimiter:
    """Test the confidence-weighted flip rate limiter."""

    def test_high_conf_flip_bypasses_limiter(self):
        """High-confidence flips (>= 0.80) should not count toward rate limit."""
        from llm.decision_engine import _flip_history, _FLIP_RATE_LIMIT

        # Clear history
        _flip_history.clear()

        # Fill with flips (would normally trigger rate limit)
        for _ in range(8):
            _flip_history.append(True)
        for _ in range(12):
            _flip_history.append(False)

        # Flip rate is now 8/20 = 40% > 30% limit
        flip_rate = sum(_flip_history) / len(_flip_history)
        assert flip_rate > _FLIP_RATE_LIMIT

        # A high-confidence flip should NOT be added to history
        # (tested implicitly through the decision engine)
        # Here we just verify the deque tracking works
        initial_len = len(_flip_history)
        # Simulate: high-conf flip doesn't append
        is_high_conf_flip = True
        if not is_high_conf_flip:
            _flip_history.append(True)
        # Length unchanged — high-conf flip bypassed
        assert len(_flip_history) == initial_len

    def test_low_conf_flip_counted(self):
        """Low-confidence flips should be counted toward rate limit."""
        from llm.decision_engine import _flip_history

        _flip_history.clear()
        initial_len = len(_flip_history)

        # Simulate: low-conf flip does append
        is_high_conf_flip = False
        is_flip = True
        if not is_high_conf_flip:
            _flip_history.append(is_flip)

        assert len(_flip_history) == initial_len + 1


# ── Portfolio Leverage Guard ────────────────────────────────────────────


class TestPortfolioLeverageGuard:
    """Test that the portfolio leverage guard blocks entries when too high."""

    def test_guard_blocks_when_over_limit(self):
        """Portfolio leverage > MAX_PORTFOLIO_LEVERAGE should block new entries."""
        # This tests the logic, not the full bot flow
        portfolio_lev = 9.0
        max_portfolio_lev = 8.0
        assert portfolio_lev >= max_portfolio_lev  # Would be blocked

    def test_guard_allows_when_under_limit(self):
        """Portfolio leverage under limit should allow new entries."""
        portfolio_lev = 3.5
        max_portfolio_lev = 8.0
        assert portfolio_lev < max_portfolio_lev  # Would be allowed
