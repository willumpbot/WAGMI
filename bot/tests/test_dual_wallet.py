"""
Tests for the Dual Wallet System.

Covers: profiles, filter chains, dispatcher, guardian, PnL tracking,
position isolation, circuit breaker independence, backward compatibility.
"""

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Ensure bot/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wallet.profile import (
    WalletProfile,
    wallet_a_default,
    wallet_b_default,
    SOURCE_ANTICIPATORY,
    SOURCE_CANDLE_PATTERN,
    SOURCE_REGIME_PREDICTION,
    SOURCE_ENSEMBLE,
    ALL_SOURCES,
    CONSERVATIVE_SOURCES,
)
from wallet.context import WalletContext
from wallet.filter_chain import WalletFilterChain, WalletFilterResult
from wallet.dispatcher import WalletDispatcher, classify_signal_source, _compute_rr_ratio
from wallet.guardian import AccountGuardian
from wallet.pnl_tracker import WalletPnLTracker, WalletTrade


# ─── Test Fixtures ────────────────────────────────────────────────────

@dataclass
class MockSignal:
    """Minimal signal for testing."""
    symbol: str = "SOL"
    side: str = "SELL"
    entry: float = 83.50
    sl: float = 84.50
    tp1: float = 80.50
    tp2: float = 78.00
    confidence: float = 85.0
    strategy: str = "anticipatory"
    atr: float = 0.8
    metadata: Dict[str, Any] = field(default_factory=dict)
    entry_reasons: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockPosition:
    """Minimal position for testing."""
    symbol: str = "BTC"
    side: str = "LONG"
    qty: float = 0.01
    entry: float = 60000.0
    leverage: float = 5.0
    state: str = "OPEN"


def _make_wallet_a() -> WalletProfile:
    """Create Wallet A profile without env var interference."""
    return WalletProfile(
        wallet_id="A",
        name="Conservative",
        allowed_sources=CONSERVATIVE_SOURCES,
        max_leverage=3.9,
        leverage_mode="half_kelly",
        min_rr_ratio=2.5,
        min_scorecard=70,
        risk_per_trade=0.0035,
        max_open_positions=3,
        equity_pct=0.5,
        cb_daily_loss_pct=0.03,
        cb_max_consecutive_losses=3,
        cb_max_drawdown_pct=0.10,
    )


def _make_wallet_b() -> WalletProfile:
    """Create Wallet B profile without env var interference."""
    return WalletProfile(
        wallet_id="B",
        name="Aggressive",
        allowed_sources=ALL_SOURCES,
        max_leverage=20.0,
        leverage_mode="conviction_tiered",
        min_rr_ratio=1.2,
        min_scorecard=50,
        risk_per_trade=0.008,
        max_open_positions=6,
        equity_pct=0.5,
        cb_daily_loss_pct=0.06,
        cb_max_consecutive_losses=5,
        cb_max_drawdown_pct=0.20,
    )


def _make_context(profile: WalletProfile, positions: dict = None) -> WalletContext:
    """Create a WalletContext with mocked components."""
    ctx = WalletContext(profile=profile)
    ctx.pos_mgr = MagicMock()
    ctx.pos_mgr.positions = positions or {}
    ctx.risk_mgr = MagicMock()
    ctx.circuit_breaker = MagicMock()
    ctx.circuit_breaker.tripped = False
    ctx.pnl_tracker = MagicMock()
    ctx._initialized = True
    return ctx


# ═══════════════════════════════════════════════════════════════════════
# PROFILE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestWalletProfile:
    """Tests for WalletProfile configuration."""

    def test_wallet_a_defaults(self):
        p = _make_wallet_a()
        assert p.wallet_id == "A"
        assert p.max_leverage == 3.9
        assert p.min_rr_ratio == 2.5
        assert p.min_scorecard == 70
        assert p.risk_per_trade == 0.0035
        assert p.max_open_positions == 3
        assert p.leverage_mode == "half_kelly"
        assert p.allowed_sources == CONSERVATIVE_SOURCES

    def test_wallet_b_defaults(self):
        p = _make_wallet_b()
        assert p.wallet_id == "B"
        assert p.max_leverage == 20.0
        assert p.min_rr_ratio == 1.2
        assert p.min_scorecard == 50
        assert p.risk_per_trade == 0.008
        assert p.max_open_positions == 6
        assert p.leverage_mode == "conviction_tiered"
        assert p.allowed_sources == ALL_SOURCES

    def test_position_key(self):
        a = _make_wallet_a()
        b = _make_wallet_b()
        assert a.position_key("BTC") == "WA:BTC"
        assert b.position_key("SOL") == "WB:SOL"
        assert a.position_key("HYPE") == "WA:HYPE"

    def test_accepts_source_conservative(self):
        a = _make_wallet_a()
        assert a.accepts_source(SOURCE_ANTICIPATORY) is True
        assert a.accepts_source(SOURCE_CANDLE_PATTERN) is False
        assert a.accepts_source(SOURCE_REGIME_PREDICTION) is False
        assert a.accepts_source(SOURCE_ENSEMBLE) is False

    def test_accepts_source_aggressive(self):
        b = _make_wallet_b()
        assert b.accepts_source(SOURCE_ANTICIPATORY) is True
        assert b.accepts_source(SOURCE_CANDLE_PATTERN) is True
        assert b.accepts_source(SOURCE_REGIME_PREDICTION) is True
        assert b.accepts_source(SOURCE_ENSEMBLE) is True

    def test_wallet_equity_50_50(self):
        a = _make_wallet_a()
        b = _make_wallet_b()
        assert a.wallet_equity(100.0) == 50.0
        assert b.wallet_equity(100.0) == 50.0

    def test_wallet_equity_custom_split(self):
        p = WalletProfile(wallet_id="A", name="Test", equity_pct=0.3)
        assert p.wallet_equity(1000.0) == 300.0

    def test_profile_is_frozen(self):
        p = _make_wallet_a()
        with pytest.raises(AttributeError):
            p.max_leverage = 10.0

    def test_env_var_loading(self):
        """Verify wallet_a_default reads from env vars."""
        with patch.dict(os.environ, {"WALLET_A_MAX_LEVERAGE": "5.0", "WALLET_A_MIN_RR": "3.0"}):
            p = wallet_a_default()
            assert p.max_leverage == 5.0
            assert p.min_rr_ratio == 3.0


# ═══════════════════════════════════════════════════════════════════════
# CONTEXT TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestWalletContext:
    """Tests for WalletContext."""

    def test_wallet_id(self):
        ctx = WalletContext(profile=_make_wallet_a())
        assert ctx.wallet_id == "A"
        assert ctx.name == "Conservative"

    def test_position_key(self):
        ctx = WalletContext(profile=_make_wallet_b())
        assert ctx.position_key("BTC") == "WB:BTC"

    def test_open_count_empty(self):
        ctx = _make_context(_make_wallet_a())
        ctx.pos_mgr.positions = {}
        assert ctx.get_open_count() == 0

    def test_open_count_with_positions(self):
        ctx = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", state="OPEN"),
            "WA:SOL": MockPosition(symbol="SOL", state="CLOSED"),
        })
        assert ctx.get_open_count() == 1

    def test_can_open_position(self):
        ctx = _make_context(_make_wallet_a())  # max 3
        ctx.pos_mgr.positions = {
            "WA:BTC": MockPosition(state="OPEN"),
            "WA:SOL": MockPosition(state="OPEN"),
        }
        assert ctx.can_open_position() is True
        ctx.pos_mgr.positions["WA:HYPE"] = MockPosition(state="OPEN")
        assert ctx.can_open_position() is False

    def test_initialize_missing_components(self):
        ctx = WalletContext(profile=_make_wallet_a())
        with pytest.raises(ValueError, match="PositionManager"):
            ctx.initialize()

    def test_initialize_success(self):
        ctx = _make_context(_make_wallet_a())
        ctx._initialized = False
        ctx.initialize()
        assert ctx.is_initialized()


# ═══════════════════════════════════════════════════════════════════════
# FILTER CHAIN TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestWalletFilterChain:
    """Tests for per-wallet signal filtering."""

    def test_source_filter_conservative_rejects_ensemble(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ENSEMBLE,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is False
        assert result.rejection_gate == "source"

    def test_source_filter_conservative_accepts_anticipatory(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is True

    def test_source_filter_aggressive_accepts_all(self):
        chain = WalletFilterChain(_make_wallet_b())
        for source in ALL_SOURCES:
            result = chain.evaluate(
                signal=MockSignal(),
                signal_source=source,
                scorecard_score=60,
                rr_ratio=2.0,
                open_count=0,
                circuit_breaker_tripped=False,
                proposed_leverage=10.0,
                equity=50.0,
            )
            assert result.approved is True, f"Source {source} should be accepted by Wallet B"

    def test_scorecard_gate_conservative(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=65,  # Below 70 threshold
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is False
        assert result.rejection_gate == "scorecard"

    def test_scorecard_gate_aggressive_passes_lower(self):
        chain = WalletFilterChain(_make_wallet_b())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=55,  # Below 70 but above 50
            rr_ratio=2.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=10.0,
            equity=50.0,
        )
        assert result.approved is True

    def test_rr_gate_conservative(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=2.0,  # Below 2.5 threshold
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is False
        assert result.rejection_gate == "rr_ratio"

    def test_rr_gate_aggressive_passes_lower(self):
        chain = WalletFilterChain(_make_wallet_b())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=60,
            rr_ratio=1.5,  # Above 1.2 threshold
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=10.0,
            equity=50.0,
        )
        assert result.approved is True

    def test_position_limit(self):
        chain = WalletFilterChain(_make_wallet_a())  # max 3
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=3,  # At limit
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is False
        assert result.rejection_gate == "position_limit"

    def test_circuit_breaker_blocks(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(confidence=80),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=True,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is False
        assert result.rejection_gate == "circuit_breaker"

    def test_circuit_breaker_override_high_confidence(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(confidence=95),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=True,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is True

    def test_leverage_capped_conservative(self):
        chain = WalletFilterChain(_make_wallet_a())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=10.0,  # Will be capped to 3.9
            equity=50.0,
        )
        assert result.approved is True
        assert result.leverage == 3.9

    def test_leverage_not_capped_aggressive(self):
        chain = WalletFilterChain(_make_wallet_b())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=60,
            rr_ratio=2.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=15.0,
            equity=50.0,
        )
        assert result.approved is True
        assert result.leverage == 15.0

    def test_leverage_capped_aggressive_at_max(self):
        chain = WalletFilterChain(_make_wallet_b())
        result = chain.evaluate(
            signal=MockSignal(),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=60,
            rr_ratio=2.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=25.0,  # Capped to 20.0
            equity=50.0,
        )
        assert result.approved is True
        assert result.leverage == 20.0

    def test_position_qty_calculated(self):
        chain = WalletFilterChain(_make_wallet_a())
        # SOL SELL: entry=83.50, sl=84.50 → stop_dist=1.20%
        # equity=50, risk=0.35% → risk_amount=$0.175
        # position_notional = $0.175 / 0.01198 = ~$14.61
        # qty = $14.61 / $83.50 = ~0.175
        result = chain.evaluate(
            signal=MockSignal(entry=83.50, sl=84.50),
            signal_source=SOURCE_ANTICIPATORY,
            scorecard_score=80,
            rr_ratio=3.0,
            open_count=0,
            circuit_breaker_tripped=False,
            proposed_leverage=3.0,
            equity=50.0,
        )
        assert result.approved is True
        assert result.position_qty > 0


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL SOURCE CLASSIFICATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestSignalClassification:
    """Tests for signal source classification."""

    def test_metadata_source(self):
        sig = MockSignal(metadata={"signal_source": "anticipatory"})
        assert classify_signal_source(sig) == "anticipatory"

    def test_entry_reasons_source(self):
        sig = MockSignal(entry_reasons={"signal_source": "candle_pattern"})
        assert classify_signal_source(sig) == "candle_pattern"

    def test_strategy_name_heuristic_anticipatory(self):
        sig = MockSignal(strategy="anticipatory_bb_upper")
        assert classify_signal_source(sig) == SOURCE_ANTICIPATORY

    def test_strategy_name_heuristic_candle(self):
        sig = MockSignal(strategy="exhaustion_reversal")
        assert classify_signal_source(sig) == SOURCE_CANDLE_PATTERN

    def test_strategy_name_heuristic_regime(self):
        sig = MockSignal(strategy="regime_pred_btc_lead")
        assert classify_signal_source(sig) == SOURCE_REGIME_PREDICTION

    def test_default_ensemble(self):
        sig = MockSignal(strategy="monte_carlo_zones")
        assert classify_signal_source(sig) == SOURCE_ENSEMBLE

    def test_rr_ratio_calculation(self):
        # SOL SELL: entry=83.50, sl=84.50, tp1=80.50
        # risk = 1.0, reward = 3.0 → R:R = 3.0
        sig = MockSignal(entry=83.50, sl=84.50, tp1=80.50)
        rr = _compute_rr_ratio(sig)
        assert rr == pytest.approx(3.0, abs=0.01)

    def test_rr_ratio_buy(self):
        # BUY: entry=100, sl=95, tp1=115 → risk=5, reward=15 → R:R=3.0
        sig = MockSignal(side="BUY", entry=100.0, sl=95.0, tp1=115.0)
        rr = _compute_rr_ratio(sig)
        assert rr == pytest.approx(3.0, abs=0.01)

    def test_rr_ratio_zero_risk(self):
        sig = MockSignal(entry=100.0, sl=100.0, tp1=105.0)
        assert _compute_rr_ratio(sig) == 0.0


# ═══════════════════════════════════════════════════════════════════════
# GUARDIAN TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestAccountGuardian:
    """Tests for cross-wallet safety."""

    def test_blocks_total_position_limit(self):
        guardian = AccountGuardian(max_total_positions=4)
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(state="OPEN"),
            "WA:SOL": MockPosition(state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b(), {
            "WB:HYPE": MockPosition(state="OPEN"),
            "WB:ETH": MockPosition(state="OPEN"),
        })
        ok, reason = guardian.can_open(ctx_a, ctx_b, "DOGE", "BUY", 100.0, "A")
        assert ok is False
        assert "Total positions" in reason

    def test_allows_within_limit(self):
        guardian = AccountGuardian(max_total_positions=10)
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b(), {
            "WB:SOL": MockPosition(state="OPEN"),
        })
        ok, reason = guardian.can_open(ctx_a, ctx_b, "HYPE", "SELL", 100.0, "A")
        assert ok is True

    def test_blocks_opposing_positions(self):
        guardian = AccountGuardian()
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", side="LONG", state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b())
        # B tries to SHORT BTC while A is LONG
        ok, reason = guardian.can_open(ctx_a, ctx_b, "BTC", "SHORT", 100.0, "B")
        assert ok is False
        assert "Opposing" in reason

    def test_allows_same_direction(self):
        guardian = AccountGuardian()
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", side="LONG", state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b())
        # B also LONG BTC — OK on exchange (additive)
        ok, reason = guardian.can_open(ctx_a, ctx_b, "BTC", "BUY", 100.0, "B")
        assert ok is True

    def test_allows_different_symbol(self):
        guardian = AccountGuardian()
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", side="LONG", state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b())
        ok, reason = guardian.can_open(ctx_a, ctx_b, "SOL", "SHORT", 100.0, "B")
        assert ok is True

    def test_ignores_closed_positions(self):
        guardian = AccountGuardian()
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", side="LONG", state="CLOSED"),
        })
        ctx_b = _make_context(_make_wallet_b())
        ok, reason = guardian.can_open(ctx_a, ctx_b, "BTC", "SHORT", 100.0, "B")
        assert ok is True

    def test_combined_exposure(self):
        guardian = AccountGuardian()
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(state="OPEN", qty=0.01, entry=60000, leverage=5),
        })
        ctx_b = _make_context(_make_wallet_b(), {
            "WB:SOL": MockPosition(state="OPEN", qty=10, entry=80, leverage=10),
        })
        exposure = guardian.get_combined_exposure(ctx_a, ctx_b)
        assert exposure["total_positions"] == 2
        assert exposure["wallet_a_positions"] == 1
        assert exposure["wallet_b_positions"] == 1


# ═══════════════════════════════════════════════════════════════════════
# DISPATCHER TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestWalletDispatcher:
    """Tests for signal dispatching to both wallets."""

    def _make_dispatcher(self) -> tuple:
        """Create dispatcher with both wallet contexts."""
        ctx_a = _make_context(_make_wallet_a())
        ctx_b = _make_context(_make_wallet_b())
        guardian = AccountGuardian()
        dispatcher = WalletDispatcher(ctx_a, ctx_b, guardian)
        return dispatcher, ctx_a, ctx_b

    def test_anticipatory_signal_both_wallets(self):
        """High-quality anticipatory signal passes both wallets."""
        d, _, _ = self._make_dispatcher()
        signal = MockSignal(entry=83.50, sl=84.50, tp1=80.50)  # R:R=3.0
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=80,
            proposed_leverage=3.9,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        assert len(approvals) == 2
        wallet_ids = {ctx.wallet_id for ctx, _ in approvals}
        assert wallet_ids == {"A", "B"}

    def test_candle_pattern_aggressive_only(self):
        """Candle pattern signal only passes Wallet B."""
        d, _, _ = self._make_dispatcher()
        signal = MockSignal(
            strategy="exhaustion_reversal",
            entry=83.50, sl=84.50, tp1=80.50,
        )
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=60,
            proposed_leverage=12.0,
            total_equity=100.0,
            signal_source=SOURCE_CANDLE_PATTERN,
        )
        assert len(approvals) == 1
        assert approvals[0][0].wallet_id == "B"

    def test_low_rr_rejected_by_conservative(self):
        """Signal with R:R 1.5 passes B (min 1.2) but not A (min 2.5)."""
        d, _, _ = self._make_dispatcher()
        # R:R = 1.5 (entry=100, sl=98, tp1=103 → risk=2, reward=3)
        signal = MockSignal(entry=100.0, sl=98.0, tp1=103.0)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=75,
            proposed_leverage=10.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        assert len(approvals) == 1
        assert approvals[0][0].wallet_id == "B"

    def test_low_scorecard_rejected_by_conservative(self):
        """Score 55 passes B (min 50) but not A (min 70)."""
        d, _, _ = self._make_dispatcher()
        signal = MockSignal(entry=83.50, sl=84.50, tp1=80.50)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=55,
            proposed_leverage=3.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        assert len(approvals) == 1
        assert approvals[0][0].wallet_id == "B"

    def test_junk_signal_rejected_by_both(self):
        """Very low quality signal rejected by both wallets."""
        d, _, _ = self._make_dispatcher()
        signal = MockSignal(entry=100.0, sl=99.0, tp1=100.5)  # R:R=0.5
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=30,
            proposed_leverage=2.0,
            total_equity=100.0,
            signal_source=SOURCE_ENSEMBLE,
        )
        assert len(approvals) == 0

    def test_guardian_blocks_opposing(self):
        """Guardian blocks when other wallet has opposing position."""
        ctx_a = _make_context(_make_wallet_a(), {
            "WA:BTC": MockPosition(symbol="BTC", side="LONG", state="OPEN"),
        })
        ctx_b = _make_context(_make_wallet_b())
        guardian = AccountGuardian()
        d = WalletDispatcher(ctx_a, ctx_b, guardian)

        signal = MockSignal(symbol="BTC", side="SELL", entry=60000, sl=61000, tp1=57000)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=80,
            proposed_leverage=10.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        # B should be blocked by guardian (opposing A's LONG)
        b_approvals = [ctx for ctx, _ in approvals if ctx.wallet_id == "B"]
        assert len(b_approvals) == 0

    def test_leverage_capped_per_wallet(self):
        """Conservative wallet caps at 3.9x, aggressive at 20x."""
        d, _, _ = self._make_dispatcher()
        signal = MockSignal(entry=83.50, sl=84.50, tp1=80.50)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=80,
            proposed_leverage=15.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        for ctx, result in approvals:
            if ctx.wallet_id == "A":
                assert result.leverage == 3.9
            elif ctx.wallet_id == "B":
                assert result.leverage == 15.0


# ═══════════════════════════════════════════════════════════════════════
# PNL TRACKER TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestWalletPnLTracker:
    """Tests for per-wallet P&L tracking."""

    def test_initial_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            assert tracker.equity == 50.0
            assert tracker.total_trades == 0
            assert tracker.win_rate == 0.0

    def test_record_winning_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            trade = WalletTrade(
                trade_id="T1", wallet_id="A", symbol="SOL", side="SELL",
                entry=83.50, exit_price=80.50, qty=0.5, leverage=3.9,
                pnl=1.50, fees=0.05, net_pnl=1.45, hold_time_s=3600,
                outcome="CLEAN_WIN", signal_source="anticipatory",
                scorecard_score=80, opened_at="2026-03-29T18:00:00Z",
                closed_at="2026-03-29T19:00:00Z",
            )
            tracker.record_trade(trade)
            assert tracker.equity == 51.45
            assert tracker.wins == 1
            assert tracker.total_trades == 1
            assert tracker.win_rate == 100.0

    def test_record_losing_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("B", 50.0, data_dir=tmpdir)
            trade = WalletTrade(
                trade_id="T2", wallet_id="B", symbol="HYPE", side="BUY",
                entry=40.0, exit_price=39.0, qty=1.0, leverage=10.0,
                pnl=-1.0, fees=0.03, net_pnl=-1.03, hold_time_s=1800,
                outcome="CLEAN_LOSS", signal_source="candle_pattern",
                scorecard_score=55, opened_at="2026-03-29T18:00:00Z",
                closed_at="2026-03-29T18:30:00Z",
            )
            tracker.record_trade(trade)
            assert tracker.equity == pytest.approx(48.97, abs=0.01)
            assert tracker.losses == 1
            assert tracker.max_drawdown > 0

    def test_separate_tracking(self):
        """Two trackers don't interfere with each other."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_a = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            tracker_b = WalletPnLTracker("B", 50.0, data_dir=tmpdir)

            win = WalletTrade(
                trade_id="T1", wallet_id="A", symbol="SOL", side="SELL",
                entry=83.50, exit_price=80.50, qty=0.5, leverage=3.9,
                pnl=1.50, fees=0.05, net_pnl=1.45, hold_time_s=3600,
                outcome="CLEAN_WIN", signal_source="anticipatory",
                scorecard_score=80, opened_at="2026-03-29T18:00:00Z",
                closed_at="2026-03-29T19:00:00Z",
            )
            loss = WalletTrade(
                trade_id="T2", wallet_id="B", symbol="HYPE", side="BUY",
                entry=40.0, exit_price=39.0, qty=1.0, leverage=10.0,
                pnl=-1.0, fees=0.03, net_pnl=-1.03, hold_time_s=1800,
                outcome="CLEAN_LOSS", signal_source="candle_pattern",
                scorecard_score=55, opened_at="2026-03-29T18:00:00Z",
                closed_at="2026-03-29T18:30:00Z",
            )

            tracker_a.record_trade(win)
            tracker_b.record_trade(loss)

            assert tracker_a.equity == 51.45
            assert tracker_b.equity == pytest.approx(48.97, abs=0.01)
            assert tracker_a.wins == 1
            assert tracker_b.losses == 1

    def test_persistence(self):
        """Tracker state persists across restarts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            trade = WalletTrade(
                trade_id="T1", wallet_id="A", symbol="SOL", side="SELL",
                entry=83.50, exit_price=80.50, qty=0.5, leverage=3.9,
                pnl=1.50, fees=0.05, net_pnl=1.45, hold_time_s=3600,
                outcome="CLEAN_WIN", signal_source="anticipatory",
                scorecard_score=80, opened_at="2026-03-29T18:00:00Z",
                closed_at="2026-03-29T19:00:00Z",
            )
            tracker.record_trade(trade)

            # Reload
            tracker2 = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            assert tracker2.equity == 51.45
            assert tracker2.total_trades == 1

    def test_daily_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            tracker.daily_pnl = 5.0
            tracker.reset_daily()
            assert tracker.daily_pnl == 0.0

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = WalletPnLTracker("A", 50.0, data_dir=tmpdir)
            summary = tracker.get_summary()
            assert summary['wallet_id'] == 'A'
            assert summary['equity'] == 50.0
            assert summary['total_trades'] == 0


# ═══════════════════════════════════════════════════════════════════════
# POSITION ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestPositionIsolation:
    """Tests for position isolation between wallets."""

    def test_wallet_id_on_position(self):
        """Position dataclass has wallet_id field."""
        from execution.position_manager import Position
        pos = Position(
            symbol="BTC", side="LONG", entry=60000,
            qty=0.01, sl=58000, tp1=62000, tp2=65000,
            wallet_id="A",
        )
        assert pos.wallet_id == "A"

    def test_wallet_id_default_empty(self):
        """Backward compat: wallet_id defaults to empty string."""
        from execution.position_manager import Position
        pos = Position(
            symbol="BTC", side="LONG", entry=60000,
            qty=0.01, sl=58000, tp1=62000, tp2=65000,
        )
        assert pos.wallet_id == ""

    def test_separate_position_keys(self):
        """Wallet A and B have different position keys for same symbol."""
        a = _make_wallet_a()
        b = _make_wallet_b()
        assert a.position_key("BTC") != b.position_key("BTC")
        assert "WA" in a.position_key("BTC")
        assert "WB" in b.position_key("BTC")


# ═══════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER INDEPENDENCE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestCircuitBreakerIndependence:
    """Tests that circuit breakers are independent per wallet."""

    def test_tripped_a_doesnt_affect_b(self):
        """Tripping CB in wallet A does not block wallet B."""
        d, ctx_a, ctx_b = TestWalletDispatcher()._make_dispatcher()

        # Trip wallet A's circuit breaker
        ctx_a.circuit_breaker.tripped = True

        signal = MockSignal(entry=83.50, sl=84.50, tp1=80.50, confidence=80)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=80,
            proposed_leverage=10.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )

        # A should be blocked (CB tripped, confidence 80 < 92 override threshold)
        # B should pass
        wallet_ids = {ctx.wallet_id for ctx, _ in approvals}
        assert "A" not in wallet_ids
        assert "B" in wallet_ids

    def test_both_tripped_both_blocked(self):
        """Both wallets blocked when both CBs tripped."""
        ctx_a = _make_context(_make_wallet_a())
        ctx_b = _make_context(_make_wallet_b())
        ctx_a.circuit_breaker.tripped = True
        ctx_b.circuit_breaker.tripped = True
        guardian = AccountGuardian()
        d = WalletDispatcher(ctx_a, ctx_b, guardian)

        signal = MockSignal(entry=83.50, sl=84.50, tp1=80.50, confidence=80)
        approvals = d.dispatch(
            signal=signal,
            scorecard_score=80,
            proposed_leverage=10.0,
            total_equity=100.0,
            signal_source=SOURCE_ANTICIPATORY,
        )
        assert len(approvals) == 0


# ═══════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Tests for backward compatibility with single-wallet mode."""

    def test_trading_config_flag_default_off(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.dual_wallet_enabled is False

    def test_trading_config_equity_split_defaults(self):
        from trading_config import TradingConfig
        config = TradingConfig()
        assert config.wallet_a_equity_pct == 0.5
        assert config.wallet_b_equity_pct == 0.5

    def test_position_wallet_id_backward_compat(self):
        """Existing Position usage works without wallet_id."""
        from execution.position_manager import Position
        pos = Position(
            symbol="BTC", side="LONG", entry=60000,
            qty=0.01, sl=58000, tp1=62000, tp2=65000,
        )
        # All existing functionality should work
        assert pos.symbol == "BTC"
        assert pos.wallet_id == ""
        assert pos.state == "IDLE"
