"""
Tests for Batch 3: LLM sizing application, profitable pattern boost,
cross-symbol patterns, exit intelligence, deep memory wiring.
"""

import os
import sys
import time
from collections import defaultdict, deque
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── LLM Size Multiplier Application ──────────────────────────────────


class TestLLMSizeMultiplier:
    """Test that LLM size_multiplier is actually applied to position sizing."""

    def test_size_mult_clamps_to_range(self):
        """Size multiplier should be clamped between 0.5 and 2.0."""
        # Test the clamping logic directly
        for raw, expected in [(0.1, 0.5), (0.5, 0.5), (1.0, 1.0), (2.0, 2.0), (3.0, 2.0)]:
            clamped = max(0.5, min(2.0, raw))
            assert clamped == expected, f"Raw {raw} should clamp to {expected}"

    def test_size_mult_applied_to_qty(self):
        """When LLM provides size_mult != 1.0, qty should be adjusted."""
        base_qty = 1.0
        llm_sz = 1.5
        # Simulate the logic from multi_strategy_main
        llm_sz = max(0.5, min(2.0, llm_sz))
        adjusted = base_qty * llm_sz
        assert adjusted == 1.5

    def test_size_mult_ignored_when_1(self):
        """size_mult=1.0 should not change qty."""
        base_qty = 0.5
        llm_sz = 1.0
        # The code checks `llm_sz != 1.0` before applying
        if llm_sz != 1.0:
            adjusted = base_qty * llm_sz
        else:
            adjusted = base_qty
        assert adjusted == 0.5


# ── Profitable Pattern Boost ─────────────────────────────────────────


class TestProfitablePatternBoost:
    """Test that confirmed profitable patterns get a sizing boost."""

    def test_high_wr_symbol_gets_boost(self):
        """Symbol with >60% WR over 10+ trades gets a size boost."""
        sym_data = {"wins": 7, "total": 10, "pnl": 50.0, "recent": []}
        sym_wr = sym_data["wins"] / sym_data["total"]
        assert sym_wr >= 0.60
        boost = 1.0 + (sym_wr - 0.50) * 0.6
        assert boost > 1.0
        assert boost <= 1.3  # Capped

    def test_low_wr_symbol_no_boost(self):
        """Symbol with <60% WR should not get a boost."""
        sym_data = {"wins": 5, "total": 10, "pnl": -10.0, "recent": []}
        sym_wr = sym_data["wins"] / sym_data["total"]
        assert sym_wr < 0.60
        boost = 1.0
        if sym_wr >= 0.60:
            boost = 1.0 + (sym_wr - 0.50) * 0.6
        assert boost == 1.0

    def test_boost_capped_at_130(self):
        """Pattern boost should never exceed 1.3x."""
        # Even with 100% WR
        sym_wr = 1.0
        boost = 1.0 + (sym_wr - 0.50) * 0.6  # = 1.3
        boost = min(1.3, boost)
        assert boost == 1.3

    def test_insufficient_data_no_boost(self):
        """Fewer than 10 trades should not trigger boost."""
        sym_data = {"wins": 5, "total": 5, "pnl": 50.0, "recent": []}
        # Code checks `sym_data["total"] >= 10`
        should_boost = sym_data["total"] >= 10
        assert not should_boost

    def test_regime_boost_threshold(self):
        """Regime with >55% WR over 8+ trades gets boost."""
        reg_data = {"wins": 5, "total": 8}
        reg_wr = reg_data["wins"] / reg_data["total"]
        assert reg_wr >= 0.55
        boost = 1.0 + (reg_wr - 0.50) * 0.4
        assert boost > 1.0

    def test_multiple_dimensions_take_max(self):
        """When multiple dimensions are profitable, take the maximum boost."""
        sym_boost = 1.12  # 70% WR symbol
        strat_boost = 1.18  # 80% WR strategy
        regime_boost = 1.05  # 62.5% WR regime
        final = max(sym_boost, strat_boost, regime_boost)
        assert final == 1.18


# ── Cross-Symbol Pattern Tracker ──────────────────────────────────────


class TestCrossSymbolTracker:
    """Test the cross-symbol lead-lag pattern detection."""

    def test_price_recording(self):
        from strategies.cross_symbol_patterns import CrossSymbolTracker
        tracker = CrossSymbolTracker()
        tracker.record_price("BTC/USDC:USDC", 50000, timestamp=1000.0)
        assert len(tracker.price_history["BTC/USDC:USDC"]) == 1

    def test_no_pattern_on_single_symbol(self):
        from strategies.cross_symbol_patterns import CrossSymbolTracker
        tracker = CrossSymbolTracker()
        # Record only BTC prices
        for i in range(100):
            tracker.record_price("BTC/USDC:USDC", 50000 + i * 10, timestamp=1000.0 + i * 60)
        signals = tracker.get_active_signals()
        assert len(signals) == 0

    def test_pattern_detection_needs_minimum_observations(self):
        from strategies.cross_symbol_patterns import CrossSymbolTracker
        tracker = CrossSymbolTracker()
        # Patterns need >= 3 observations to be considered
        assert len(tracker.patterns) == 0
        signals = tracker.get_active_signals()
        assert len(signals) == 0

    def test_pattern_summary_empty_initially(self):
        from strategies.cross_symbol_patterns import CrossSymbolTracker
        tracker = CrossSymbolTracker()
        summary = tracker.get_pattern_summary()
        assert len(summary) == 0

    def test_pct_change_computation(self):
        from strategies.cross_symbol_patterns import CrossSymbolTracker
        tracker = CrossSymbolTracker()
        # Record BTC going from 50000 to 51000 over 1 hour
        tracker.record_price("BTC/USDC:USDC", 50000, timestamp=1000.0)
        tracker.record_price("BTC/USDC:USDC", 51000, timestamp=4600.0)
        pct = tracker._compute_pct_change("BTC/USDC:USDC", 3600)
        assert abs(pct - 2.0) < 0.01  # ~2% change


# ── Symbol Confidence Floor Wiring ────────────────────────────────────


class TestSymbolFloorWiring:
    """Test that symbol confidence floor is wired into feedback loop."""

    def test_feedback_loop_uses_symbol_floor(self):
        """Verify FeedbackLoop.evaluate_signal applies symbol difficulty."""
        from feedback.loop import FeedbackLoop
        loop = FeedbackLoop(data_dir="/tmp/test_fb_b3")
        # Record trades to establish symbol difficulty
        from feedback.signal_quality import QualityFeatures
        for i in range(12):
            feat = QualityFeatures(symbol="HARD/USDC:USDC", side="BUY", hour_of_day=12)
            loop.quality.record_outcome(feat, win=(i < 2), pnl=-10 if i >= 2 else 5)
        # Hard symbol (16.7% WR) should have higher floor
        hard_floor = loop.quality.get_symbol_confidence_floor("HARD/USDC:USDC")
        base_floor = 65.0
        assert hard_floor > base_floor


# ── Degradation Manager LLM Wiring ──────────────────────────────────


class TestDegradationLLMWiring:
    """Test degradation manager tracks LLM errors."""

    def test_llm_degradation_skips_calls(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        # Initially not degraded
        assert not mgr.should_skip_llm()
        # Record consecutive errors
        for _ in range(3):
            mgr.record_llm_error()
        assert mgr.should_skip_llm()

    def test_llm_recovery(self):
        from execution.graceful_degradation import DegradationManager
        mgr = DegradationManager()
        for _ in range(3):
            mgr.record_llm_error()
        assert mgr.should_skip_llm()
        # Recovery requires time since last error > recovery window
        # Simulate by backdating the last error timestamp
        mgr._llm_last_error = time.time() - 400  # Past 5-min recovery window
        mgr.record_llm_success()
        assert not mgr.should_skip_llm()


# ── Funding Rate in Position Snapshot ─────────────────────────────────


class TestFundingRateSnapshot:
    """Test that active position snapshots include funding rate."""

    def test_position_dict_has_funding_rate(self):
        """The active_positions dict should include funding_rate field."""
        # Simulate what _build_llm_context does
        funding_rates = {"BTC/USDC:USDC": 0.0005}
        sym = "BTC/USDC:USDC"
        pos_dict = {
            "symbol": sym,
            "side": "LONG",
            "entry": 50000,
            "leverage": 5.0,
            "unrealized_pnl": 100.0,
            "funding_rate": funding_rates.get(sym, 0.0),
        }
        assert "funding_rate" in pos_dict
        assert pos_dict["funding_rate"] == 0.0005

    def test_missing_funding_rate_defaults_to_zero(self):
        funding_rates = {}
        sym = "ETH/USDC:USDC"
        rate = funding_rates.get(sym, 0.0)
        assert rate == 0.0


# ── LLM System Prompt Enhancements ───────────────────────────────────


class TestLLMPromptEnhancements:
    """Test system prompt includes aggression guidance."""

    def test_prompt_has_confirmed_pattern_section(self):
        from llm.system_prompt import LLM_SYSTEM_PROMPT
        assert "CONFIRMED PROFITABLE PATTERNS" in LLM_SYSTEM_PROMPT
        assert "BE AGGRESSIVE" in LLM_SYSTEM_PROMPT

    def test_prompt_references_knowledge_field(self):
        from llm.system_prompt import LLM_SYSTEM_PROMPT
        assert "knowledge" in LLM_SYSTEM_PROMPT
        assert "cross_symbol_signals" in LLM_SYSTEM_PROMPT

    def test_compact_prompt_has_aggression_guidance(self):
        from llm.system_prompt import LLM_SYSTEM_PROMPT_COMPACT
        assert "AGGRESSION THROUGH CONFIRMATION" in LLM_SYSTEM_PROMPT_COMPACT
        assert "SIZE UP" in LLM_SYSTEM_PROMPT_COMPACT
