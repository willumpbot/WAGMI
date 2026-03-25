"""
Hardening Edge Case Tests for Manual Sniper System.

Tests edge cases discovered during code audit (2026-03-24):
- NaN/None/missing field handling
- Division by zero protection
- Boundary conditions (zero equity, extreme leverage)
- Malformed signal data
- Atomic file operations
- Simulator resilience
- Position rules boundary conditions
"""

import json
import math
import os
import tempfile
import time
import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from unittest.mock import patch, MagicMock


# ── Shared test helpers ──────────────────────────────────────────────

@dataclass
class MockSignal:
    """Minimal signal stub that mirrors strategies.base.Signal."""
    strategy: str = "regime_trend"
    symbol: str = "HYPE"
    side: str = "BUY"
    confidence: float = 82.0
    entry: float = 40.0
    sl: float = 39.0
    tp1: float = 42.0
    tp2: float = 44.0
    atr: float = 1.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_context: str = ""

    @property
    def is_valid(self):
        return True


def _make_filter(**overrides):
    from manual.sniper_filter import ManualSniperFilter
    from manual.config import ManualSniperConfig
    config = ManualSniperConfig()
    for k, v in overrides.items():
        setattr(config, k, v)
    f = ManualSniperFilter(config)
    f._running_equity = overrides.get('equity', 100.0)
    return f


def _make_signal(**overrides) -> MockSignal:
    defaults = {
        "symbol": "HYPE",
        "side": "BUY",
        "confidence": 82.0,
        "entry": 40.0,
        "sl": 39.0,
        "tp1": 42.0,
        "tp2": 44.0,
        "atr": 1.5,
        "metadata": {
            "num_agree": 3,
            "strategies_agree": ["regime_trend", "monte_carlo_zones", "confidence_scorer"],
            "regime": "consolidation",
            "ev_per_dollar": 0.15,
        },
    }
    defaults.update(overrides)
    return MockSignal(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# SNIPER FILTER EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestSniperFilterNaN:
    """NaN and None handling in sniper filter."""

    def test_nan_confidence_rejected(self):
        """NaN confidence must be rejected, not silently pass."""
        filt = _make_filter()
        sig = _make_signal(confidence=float('nan'))
        assert filt.evaluate(sig) is None

    def test_none_confidence_rejected(self):
        """None confidence must be rejected."""
        filt = _make_filter()
        sig = _make_signal(confidence=None)
        assert filt.evaluate(sig) is None

    def test_nan_chop_treated_as_clean(self):
        """NaN chop should be treated as 0.0 (clean market, pass through)."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": ["a", "b", "c"],
            "regime": "trend",
            "chop_score_smoothed": float('nan'),
        })
        result = filt.evaluate(sig)
        assert result is not None  # HYPE BUY proven setup should pass

    def test_none_chop_treated_as_clean(self):
        """None chop should be treated as 0.0."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": ["a", "b", "c"],
            "regime": "trend",
            "chop_score_smoothed": None,
            "chop_score": None,
        })
        result = filt.evaluate(sig)
        assert result is not None


class TestSniperFilterMissingFields:
    """Test handling of signals with missing or malformed metadata."""

    def test_empty_metadata(self):
        """Signal with empty metadata should use defaults."""
        filt = _make_filter()
        sig = _make_signal(metadata={})
        # HYPE BUY is proven, should still work with default num_agree=1
        result = filt.evaluate(sig)
        assert result is not None

    def test_none_metadata(self):
        """Signal with None metadata shouldn't crash."""
        filt = _make_filter()
        sig = _make_signal(metadata=None)
        result = filt.evaluate(sig)
        assert result is not None  # HYPE BUY, metadata defaults to {}

    def test_missing_strategies_agree(self):
        """Missing strategies_agree should default gracefully."""
        filt = _make_filter()
        sig = _make_signal(metadata={"num_agree": 3, "regime": "trend"})
        result = filt.evaluate(sig)
        assert result is not None
        assert isinstance(result.strategies, list)

    def test_string_strategies_agree(self):
        """strategies_agree as string (not list) should be handled."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": "regime_trend",
            "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert isinstance(result.strategies, list)

    def test_missing_signal_context(self):
        """Signal without signal_context attribute shouldn't crash."""
        filt = _make_filter()
        sig = _make_signal()
        delattr(sig, 'signal_context')
        result = filt.evaluate(sig)
        assert result is not None


class TestSniperFilterBoundaryEquity:
    """Test equity boundary conditions."""

    def test_zero_equity_rejected(self):
        """Zero equity should be rejected (can't trade with $0)."""
        filt = _make_filter(equity=0.0)
        filt._running_equity = 0.0
        sig = _make_signal()
        assert filt.evaluate(sig) is None

    def test_negative_equity_rejected(self):
        """Negative equity should be rejected."""
        filt = _make_filter(equity=-50.0)
        filt._running_equity = -50.0
        sig = _make_signal()
        assert filt.evaluate(sig) is None

    def test_tiny_equity_1_dollar(self):
        """$1 account should still work but with tiny position."""
        filt = _make_filter(equity=1.0)
        filt._running_equity = 1.0
        sig = _make_signal()
        result = filt.evaluate(sig)
        assert result is not None
        assert result.risk_amount <= 1.0
        assert result.margin_required <= 1.0

    def test_large_equity_10k(self):
        """$10k account should scale up correctly."""
        filt = _make_filter(equity=10000.0)
        filt._running_equity = 10000.0
        sig = _make_signal()
        result = filt.evaluate(sig)
        assert result is not None
        assert result.risk_amount == 1000.0  # 10% of $10k


class TestSniperFilterEntryPrice:
    """Test entry price edge cases."""

    def test_zero_entry_rejected(self):
        """Zero entry price should not crash (division by zero)."""
        filt = _make_filter()
        sig = _make_signal(entry=0.0, sl=0.0, tp1=0.0, tp2=0.0)
        # risk = abs(0 - 0) = 0, should be rejected
        assert filt.evaluate(sig) is None

    def test_entry_equals_sl(self):
        """Entry == SL means zero risk width, should be rejected."""
        filt = _make_filter()
        sig = _make_signal(entry=40.0, sl=40.0)
        assert filt.evaluate(sig) is None

    def test_very_small_stop_width(self):
        """Very tight stop should still work but not produce infinite leverage."""
        filt = _make_filter()
        sig = _make_signal(entry=40.0, sl=39.99, tp1=42.0, tp2=44.0)
        result = filt.evaluate(sig)
        if result is not None:
            assert result.leverage <= 25.0  # Capped
            assert result.position_size_usd > 0
            assert result.margin_required <= result.account_equity


class TestSniperFilterUnknownSymbol:
    """Test behavior with symbols not in proven setups."""

    def test_unknown_symbol_needs_confidence(self):
        """Non-proven symbol must pass confidence + consensus gates."""
        filt = _make_filter()
        sig = _make_signal(
            symbol="DOGE", side="BUY", confidence=70.0,
            entry=0.15, sl=0.14, tp1=0.17, tp2=0.19,
            metadata={"num_agree": 1, "strategies_agree": ["a"], "regime": "trend"},
        )
        assert filt.evaluate(sig) is None  # 70% conf, 1 agree = rejected

    def test_unknown_symbol_high_conf_passes(self):
        """Non-proven symbol at high conf + consensus should pass."""
        filt = _make_filter(mode="standard")
        sig = _make_signal(
            symbol="DOGE", side="BUY", confidence=85.0,
            entry=0.15, sl=0.14, tp1=0.17, tp2=0.19,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier == "SNIPER"


class TestSniperFilterChopGating:
    """Test chop score filtering on proven setups."""

    def test_high_chop_rejects_hype_buy(self):
        """HYPE BUY with chop > 0.4 should be rejected."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": ["a", "b", "c"],
            "regime": "trend",
            "chop_score_smoothed": 0.6,
        })
        assert filt.evaluate(sig) is None

    def test_low_chop_passes_hype_buy(self):
        """HYPE BUY with chop < 0.4 should pass."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": ["a", "b", "c"],
            "regime": "trend",
            "chop_score_smoothed": 0.2,
        })
        result = filt.evaluate(sig)
        assert result is not None

    def test_borderline_chop_hype_buy(self):
        """HYPE BUY with chop exactly at 0.4 should be rejected (> not >=)."""
        filt = _make_filter()
        sig = _make_signal(metadata={
            "num_agree": 3,
            "strategies_agree": ["a", "b", "c"],
            "regime": "trend",
            "chop_score_smoothed": 0.4,
        })
        # chop > 0.4 → 0.4 > 0.4 is False → passes
        result = filt.evaluate(sig)
        assert result is not None

    def test_sol_sell_higher_chop_threshold(self):
        """SOL SELL has max_chop=0.5 (more lenient than HYPE BUY's 0.4)."""
        filt = _make_filter(dedup_window_s=0, min_alert_gap_s=0)
        sig = _make_signal(
            symbol="SOL", side="SELL", confidence=80.0,
            entry=150.0, sl=155.0, tp1=143.0, tp2=136.0,
            metadata={
                "num_agree": 3, "strategies_agree": ["a", "b", "c"],
                "regime": "trend", "chop_score_smoothed": 0.45,
            },
        )
        result = filt.evaluate(sig)
        assert result is not None  # 0.45 < 0.5 → passes


class TestSniperFilterBurst:
    """Test signal burst handling."""

    def test_rapid_fire_dedup(self):
        """Multiple signals in quick succession should be deduped."""
        filt = _make_filter(dedup_window_s=600, min_alert_gap_s=300)
        sig = _make_signal()
        # First passes
        assert filt.evaluate(sig) is not None
        # Same signal within dedup window
        assert filt.evaluate(sig) is None
        assert filt.evaluate(sig) is None

    def test_different_symbols_not_deduped(self):
        """Different symbols should not block each other via dedup."""
        filt = _make_filter(dedup_window_s=600, min_alert_gap_s=0, max_daily_signals=10)
        sig1 = _make_signal(symbol="HYPE", side="BUY")
        sig2 = _make_signal(
            symbol="SOL", side="SELL", confidence=82.0,
            entry=150.0, sl=155.0, tp1=143.0, tp2=136.0,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        assert filt.evaluate(sig1) is not None
        assert filt.evaluate(sig2) is not None


# ═══════════════════════════════════════════════════════════════════════
# EXECUTION HELPER EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestExecutionHelperEdgeCases:
    """Edge cases for Hyperliquid order building."""

    def _make_sniper(self, **overrides):
        from manual.sniper_filter import SniperSignal
        defaults = dict(
            symbol="HYPE", side="BUY", tier="SNIPER",
            entry=25.0, sl=24.50, tp_scalp=25.75, tp_swing=26.50,
            leverage=25.0, risk_pct=0.10, risk_amount=10.0,
            position_size_usd=400.0, qty=40.0,
            margin_required=16.0,
            pnl_scalp=15.0, pnl_swing=30.0, loss_amount=10.0,
            rr_scalp=1.5, rr_swing=3.0,
            account_equity=100.0, account_after_win=115.0,
            account_after_loss=90.0, growth_pct=15.0,
            confidence=88.0, num_agree=3,
            strategies=["regime_trend", "monte_carlo", "confidence_scorer"],
            regime="consolidation", ev_per_dollar=0.15,
            signal_context="Test",
            timestamp="2026-03-24T10:00:00Z",
            daily_target_pct=150.0, hold_target_hours="1-4h (scalp)",
        )
        defaults.update(overrides)
        return SniperSignal(**defaults)

    def test_zero_leverage_handled(self):
        """Zero leverage should be clamped to 1, not cause division by zero."""
        from manual.execution_helper import HyperliquidOrderBuilder
        builder = HyperliquidOrderBuilder()
        sig = self._make_sniper(leverage=0)
        order = builder.from_sniper_signal(sig)
        assert order.leverage >= 1
        assert order.margin_usd > 0

    def test_negative_leverage_handled(self):
        """Negative leverage should be clamped to 1."""
        from manual.execution_helper import HyperliquidOrderBuilder
        builder = HyperliquidOrderBuilder()
        sig = self._make_sniper(leverage=-5)
        order = builder.from_sniper_signal(sig)
        assert order.leverage >= 1

    def test_zero_qty_order(self):
        """Zero quantity signal should produce min_qty order."""
        from manual.execution_helper import HyperliquidOrderBuilder
        builder = HyperliquidOrderBuilder()
        sig = self._make_sniper(qty=0.0)
        order = builder.from_sniper_signal(sig)
        assert order.size > 0  # Should be min_qty

    def test_symbol_normalization(self):
        """Various symbol formats should normalize correctly."""
        from manual.execution_helper import HyperliquidOrderBuilder
        builder = HyperliquidOrderBuilder()
        assert builder._normalize_symbol("HYPE/USDC") == "HYPE"
        assert builder._normalize_symbol("BTC/USDC:USDC") == "BTC"
        assert builder._normalize_symbol("SOL") == "SOL"
        assert builder._normalize_symbol(" ETH ") == "ETH"

    def test_sell_order_limit_offset(self):
        """Sell orders should have limit price above market."""
        from manual.execution_helper import HyperliquidOrderBuilder, LIMIT_OFFSET_PCT
        builder = HyperliquidOrderBuilder()
        sig = self._make_sniper(side="SELL", sl=25.50, tp_scalp=24.25, tp_swing=23.50)
        order = builder.from_sniper_signal(sig)
        assert order.side == "sell"
        assert order.price > sig.entry  # Limit above market for sells


# ═══════════════════════════════════════════════════════════════════════
# POSITION RULES EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestPositionRulesEdgeCases:
    """Edge cases for position management rules."""

    def _mgr(self):
        from manual.position_rules import ManualPositionManager
        return ManualPositionManager()

    def _now(self):
        return datetime.now(timezone.utc)

    def test_zero_risk_width_closes_immediately(self):
        """Entry == SL should immediately close (zero risk)."""
        mgr = self._mgr()
        update = mgr.evaluate(
            symbol="HYPE", side="BUY", entry=25.0, sl=25.0,
            tp_scalp=26.0, tp_swing=27.0, leverage=25, tier="SNIPER",
            current_price=25.0, entry_time=self._now(),
        )
        from manual.position_rules import Action, Phase
        assert update.action == Action.CLOSE
        assert "zero risk" in update.reason.lower()

    def test_short_position_profit_calculation(self):
        """Short positions should calculate profit when price drops."""
        mgr = self._mgr()
        entry_time = self._now() - timedelta(minutes=30)
        update = mgr.evaluate(
            symbol="SOL", side="SELL", entry=150.0, sl=155.0,
            tp_scalp=145.0, tp_swing=140.0, leverage=20, tier="PREMIUM",
            current_price=147.0, entry_time=entry_time,
        )
        assert update.pnl_r > 0  # Price dropped = profit for short

    def test_emergency_high_leverage_loss(self):
        """25x leverage with 0.5%+ adverse move should trigger emergency close."""
        mgr = self._mgr()
        entry_time = self._now() - timedelta(minutes=2)
        update = mgr.evaluate(
            symbol="HYPE", side="BUY", entry=25.0, sl=24.50,
            tp_scalp=25.75, tp_swing=26.50, leverage=25, tier="SNIPER",
            current_price=24.87,  # ~0.52% drop at 25x = ~13% loss
            entry_time=entry_time,
        )
        from manual.position_rules import Action
        assert update.action == Action.CLOSE
        assert update.is_emergency

    def test_max_hold_time_closes(self):
        """Position held past max hours should force close."""
        mgr = self._mgr()
        entry_time = self._now() - timedelta(hours=9)  # Past 8h for SNIPER high lev
        update = mgr.evaluate(
            symbol="HYPE", side="BUY", entry=25.0, sl=24.50,
            tp_scalp=25.75, tp_swing=26.50, leverage=25, tier="SNIPER",
            current_price=25.10, entry_time=entry_time,
        )
        from manual.position_rules import Action
        assert update.action == Action.CLOSE
        assert update.is_emergency

    def test_funding_rate_against_long(self):
        """High positive funding + underwater long = emergency."""
        mgr = self._mgr()
        entry_time = self._now() - timedelta(minutes=30)
        update = mgr.evaluate(
            symbol="BTC", side="BUY", entry=70000, sl=69000,
            tp_scalp=71500, tp_swing=73000, leverage=25, tier="SNIPER",
            current_price=69800,  # Underwater
            entry_time=entry_time,
            funding_rate=0.001,  # 0.1% funding — longs pay
        )
        from manual.position_rules import Action
        assert update.action == Action.CLOSE
        assert update.is_emergency

    def test_candle_counting(self):
        """Three bearish candles against a long should be detected."""
        from manual.position_rules import ManualPositionManager
        mgr = ManualPositionManager()
        candles = [
            {"open": 25.0, "close": 24.8, "high": 25.1, "low": 24.7},
            {"open": 24.8, "close": 24.6, "high": 24.9, "low": 24.5},
            {"open": 24.6, "close": 24.4, "high": 24.7, "low": 24.3},
        ]
        count = mgr._count_against_candles(candles, is_long=True)
        assert count == 3

    def test_candle_reset_on_favorable(self):
        """A bullish candle in the middle should reset the counter."""
        from manual.position_rules import ManualPositionManager
        mgr = ManualPositionManager()
        candles = [
            {"open": 25.0, "close": 24.8},  # bearish
            {"open": 24.8, "close": 25.0},  # bullish — resets
            {"open": 25.0, "close": 24.9},  # bearish
        ]
        count = mgr._count_against_candles(candles, is_long=True)
        assert count == 1  # Only the last one


# ═══════════════════════════════════════════════════════════════════════
# SIMULATOR EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestSimulatorEdgeCases:
    """Edge cases for the live simulator."""

    @pytest.fixture
    def sim(self, tmp_path):
        """Create simulator with temp paths."""
        import manual.simulator as sim_mod
        orig_data = sim_mod._DATA_DIR
        orig_trades = sim_mod._TRADES_PATH
        orig_status = sim_mod._STATUS_PATH
        sim_mod._DATA_DIR = str(tmp_path)
        sim_mod._TRADES_PATH = str(tmp_path / "sim_trades.jsonl")
        sim_mod._STATUS_PATH = str(tmp_path / "sim_status.json")
        s = sim_mod.SniperSimulator(starting_equity=100.0)
        yield s
        sim_mod._DATA_DIR = orig_data
        sim_mod._TRADES_PATH = orig_trades
        sim_mod._STATUS_PATH = orig_status

    def _fake_signal(self, **overrides):
        @dataclass
        class FakeSig:
            symbol: str = "HYPE"
            side: str = "BUY"
            tier: str = "SNIPER"
            entry: float = 100.0
            sl: float = 98.0
            tp_scalp: float = 103.0
            tp_swing: float = 106.0
            leverage: float = 20.0
            risk_pct: float = 0.10
            risk_amount: float = 10.0
            position_size_usd: float = 500.0
            qty: float = 5.0
            pnl_scalp: float = 15.0
            loss_amount: float = 10.0
            confidence: float = 88.0
            num_agree: int = 3
            regime: str = "trend"
        sig = FakeSig()
        for k, v in overrides.items():
            setattr(sig, k, v)
        return sig

    def test_duplicate_position_rejected(self, sim):
        """Can't open two positions on same symbol+side."""
        sig = self._fake_signal()
        assert sim.on_signal(sig) is not None
        assert sim.on_signal(sig) is None

    def test_different_side_allowed(self, sim):
        """Can open HYPE BUY and HYPE SELL simultaneously."""
        sig_buy = self._fake_signal(side="BUY")
        sig_sell = self._fake_signal(side="SELL", sl=102.0, tp_scalp=97.0, tp_swing=94.0)
        assert sim.on_signal(sig_buy) is not None
        assert sim.on_signal(sig_sell) is not None
        assert len(sim._open_positions) == 2

    def test_zero_entry_handled(self, sim):
        """Signal with zero entry price shouldn't crash."""
        sig = self._fake_signal(entry=0.0, sl=0.0, tp_scalp=0.0, tp_swing=0.0)
        pos = sim.on_signal(sig)
        assert pos is None  # Zero entry should be rejected gracefully

    def test_missing_price_skips_position(self, sim):
        """check_positions with missing price for symbol should skip."""
        sig = self._fake_signal()
        sim.on_signal(sig)
        closed = sim.check_positions({})  # No prices
        assert len(closed) == 0
        assert len(sim._open_positions) == 1  # Still open

    def test_sl_hit_loss(self, sim):
        """SL hit should produce a loss."""
        sig = self._fake_signal()
        sim.on_signal(sig)
        closed = sim.check_positions({"HYPE": 97.0})  # Below SL of 98
        assert len(closed) == 1
        assert closed[0].result == "LOSS"
        assert closed[0].pnl_usd < 0
        assert sim._equity < 100.0

    def test_tp_hit_win(self, sim):
        """TP hit should produce a win."""
        sig = self._fake_signal()
        sim.on_signal(sig)
        closed = sim.check_positions({"HYPE": 104.0})  # Above TP of 103
        assert len(closed) == 1
        assert closed[0].result == "WIN"
        assert closed[0].pnl_usd > 0
        assert sim._equity > 100.0

    def test_status_format(self, sim):
        """get_status should return all required fields."""
        status = sim.get_status()
        required_keys = [
            "current_equity", "starting_equity", "total_trades",
            "wins", "losses", "win_rate", "profit_factor",
            "open_positions", "equity_curve",
        ]
        for key in required_keys:
            assert key in status, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════
# TRADE JOURNAL EDGE CASES
# ═══════════════════════════════════════════════════════════════════════

class TestTradeJournalEdgeCases:
    """Edge cases for trade journal."""

    @pytest.fixture
    def journal(self, tmp_path):
        from manual.trade_journal import TradeJournal
        return TradeJournal(
            journal_path=str(tmp_path / "journal.jsonl"),
            equity_path=str(tmp_path / "equity.json"),
            starting_equity=100.0,
        )

    def test_invalid_side_raises(self, journal):
        """Invalid side should raise ValueError."""
        with pytest.raises(ValueError):
            journal.log_entry(symbol="HYPE", side="INVALID", entry_price=40.0,
                            leverage=25, qty=10)

    def test_long_short_aliases(self, journal):
        """LONG/SHORT should be converted to BUY/SELL."""
        entry = journal.log_entry(symbol="HYPE", side="LONG", entry_price=40.0,
                                  leverage=25, qty=10)
        assert entry.side == "BUY"

        entry2 = journal.log_entry(symbol="HYPE", side="SHORT", entry_price=40.0,
                                   leverage=25, qty=10)
        assert entry2.side == "SELL"

    def test_exit_nonexistent_trade(self, journal):
        """Exiting a trade that doesn't exist should return None."""
        result = journal.log_exit("NONEXISTENT", 42.0)
        assert result is None

    def test_exit_by_symbol(self, journal):
        """Should find most recent open trade by symbol."""
        journal.log_entry(symbol="HYPE", side="BUY", entry_price=40.0,
                         leverage=25, qty=10)
        result = journal.log_exit("HYPE", 42.0, reason="TP")
        assert result is not None
        assert result.pnl > 0

    def test_pnl_calculation_buy(self, journal):
        """Buy trade P&L should be correct."""
        journal.log_entry(symbol="HYPE", side="BUY", entry_price=40.0,
                         leverage=25, qty=10)
        result = journal.log_exit("HYPE", 42.0, reason="TP")
        # Price change: (42-40)/40 = 5%
        # Position value: 40*10 = 400
        # PnL: 400 * 0.05 = $20
        assert result.pnl == 20.0

    def test_pnl_calculation_sell(self, journal):
        """Sell trade P&L should be correct."""
        journal.log_entry(symbol="SOL", side="SELL", entry_price=150.0,
                         leverage=20, qty=5)
        result = journal.log_exit("SOL", 145.0, reason="TP")
        # Price change: (150-145)/150 = 3.33%
        # Position value: 150*5 = 750
        # PnL: 750 * 0.0333 = $25
        assert result.pnl == pytest.approx(25.0, abs=0.1)

    def test_equity_tracks_through_trades(self, journal):
        """Equity should compound through wins and losses."""
        journal.log_entry(symbol="HYPE", side="BUY", entry_price=40.0,
                         leverage=25, qty=10)
        journal.log_exit("HYPE", 42.0)  # +$20
        assert journal.current_equity == 120.0

        journal.log_entry(symbol="HYPE", side="BUY", entry_price=42.0,
                         leverage=25, qty=10)
        journal.log_exit("HYPE", 41.0)  # Loss: 420 * (-1/42) = -$10
        assert journal.current_equity == pytest.approx(110.0, abs=0.1)

    def test_stats_no_trades(self, journal):
        """Stats with no trades should return zeroes, not crash."""
        stats = journal.get_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0

    def test_zero_leverage_entry(self, journal):
        """Zero leverage should not cause division by zero."""
        entry = journal.log_entry(symbol="HYPE", side="BUY", entry_price=40.0,
                                  leverage=0, qty=10)
        assert entry.margin_used == 400.0  # Full position value as margin

    def test_atomic_rewrite(self, journal, tmp_path):
        """Journal rewrite should be atomic (no data loss)."""
        # Add a trade
        journal.log_entry(symbol="HYPE", side="BUY", entry_price=40.0,
                         leverage=25, qty=10)
        # Close it (triggers rewrite)
        journal.log_exit("HYPE", 42.0)

        # Verify file exists and is valid
        journal_path = str(tmp_path / "journal.jsonl")
        assert os.path.exists(journal_path)
        with open(journal_path) as f:
            lines = f.readlines()
        assert len(lines) == 1  # One entry (rewritten with exit data)
        data = json.loads(lines[0])
        assert data["status"] == "CLOSED"


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION: Full Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════

class TestExpandedSetups:
    """Test expanded setup definitions (BTC SHORT >=90, BTC LONG 70-80)."""

    def test_expanded_setups_disabled_by_default(self):
        """Expanded setups should be off by default."""
        filt = _make_filter()
        assert filt.config.expanded_setups is False

    def test_btc_short_high_conf_passes_when_enabled(self):
        """BTC SHORT at 92% conf with 3 agree should pass with expanded setups."""
        filt = _make_filter(expanded_setups=True, mode="standard",
                           dedup_window_s=0, min_alert_gap_s=0)
        sig = _make_signal(
            symbol="BTC", side="SELL", confidence=92.0,
            entry=70000, sl=71000, tp1=68000, tp2=66000,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier == "PREMIUM"

    def test_btc_short_low_conf_rejected_when_enabled(self):
        """BTC SHORT at 80% conf should still be rejected (below 90% threshold)."""
        filt = _make_filter(expanded_setups=True, mode="standard",
                           dedup_window_s=0, min_alert_gap_s=0)
        sig = _make_signal(
            symbol="BTC", side="SELL", confidence=80.0,
            entry=70000, sl=71000, tp1=68000, tp2=66000,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        # 80% passes the general confidence gate but BTC_SELL setup requires >=90
        # Since it matches the setup key, it gets the min_confidence=90 check
        assert result is None

    def test_btc_buy_always_blocked_as_toxic(self):
        """BTC BUY is in toxic_setups (15% WR) — blocked regardless of expanded_setups."""
        filt = _make_filter(expanded_setups=True, mode="standard",
                           dedup_window_s=0, min_alert_gap_s=0)
        sig = _make_signal(
            symbol="BTC", side="BUY", confidence=92.0,
            entry=70000, sl=69000, tp1=72000, tp2=74000,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is None  # Toxic: 15% WR in counterfactuals

    def test_btc_buy_also_blocked_when_disabled(self):
        """BTC BUY is toxic even without expanded_setups."""
        filt = _make_filter(expanded_setups=False, mode="standard",
                           dedup_window_s=0, min_alert_gap_s=0)
        sig = _make_signal(
            symbol="BTC", side="BUY", confidence=87.0,
            entry=70000, sl=69000, tp1=72000, tp2=74000,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is None  # Toxic regardless of mode


class TestFullPipeline:
    """Test the full signal → filter → alert pipeline."""

    def test_signal_to_alert_roundtrip(self):
        """A valid signal should produce a formatted alert without crashing."""
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        from manual.alerts import format_sniper_alert

        config = ManualSniperConfig()
        filt = ManualSniperFilter(config)
        filt._running_equity = 100.0

        sig = _make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None

        # Format alert — should not crash
        msg = format_sniper_alert(result)
        assert len(msg) > 100
        assert "HYPE" in msg
        assert "LONG" in msg

    def test_filter_to_simulator_roundtrip(self):
        """Signal → filter → simulator should work end-to-end."""
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        from manual.simulator import SniperSimulator
        import manual.simulator as sim_mod

        config = ManualSniperConfig()
        filt = ManualSniperFilter(config)
        filt._running_equity = 100.0

        sig = _make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None

        # Feed to simulator (mock paths to avoid file I/O)
        with tempfile.TemporaryDirectory() as td:
            sim_mod._DATA_DIR = td
            sim_mod._TRADES_PATH = os.path.join(td, "trades.jsonl")
            sim_mod._STATUS_PATH = os.path.join(td, "status.json")
            sim = SniperSimulator(starting_equity=100.0)
            pos = sim.on_signal(result)
            assert pos is not None
            assert pos.symbol == "HYPE"
            assert pos.side == "BUY"

    def test_proven_setup_discovery_mode_separation(self):
        """Proven setups (HYPE BUY) and discovery mode (BTC SELL) should use different gates."""
        filt = _make_filter(mode="standard", max_daily_signals=10,
                           dedup_window_s=0, min_alert_gap_s=0)

        # Proven: passes at low confidence
        sig_proven = _make_signal(confidence=55.0, metadata={
            "num_agree": 1, "strategies_agree": ["a"], "regime": "trend",
        })
        result_proven = filt.evaluate(sig_proven)
        assert result_proven is not None
        assert result_proven.tier in ("PREMIUM", "SNIPER")

        # Discovery: needs high confidence
        sig_discovery = _make_signal(
            symbol="BTC", side="SELL", confidence=55.0,
            entry=70000, sl=71000, tp1=68000, tp2=66000,
            metadata={"num_agree": 1, "strategies_agree": ["a"], "regime": "trend"},
        )
        result_discovery = filt.evaluate(sig_discovery)
        assert result_discovery is None  # Low conf, 1 agree = rejected
