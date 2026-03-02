"""
Tests for Wave 1 module wiring:
  - Global Brain context injection
  - Portfolio Brain snapshot building
  - Self-Tuning Risk Engine telemetry and profile switching
  - RL buffer append/load round-trip
  - RL policy multiplier application
  - Autonomy mode constraints (DIRECTION/FULL flip gating)
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest


# ── Global Brain ─────────────────────────────────────────────

class TestGlobalBrain:
    def test_build_global_context_neutral(self):
        from llm.global_brain import build_global_context
        ctx = build_global_context(
            btc_price=60000,
            btc_1h_change=0.5,
            btc_24h_change=1.0,
            eth_price=3000,
            last_prices={"BTC": 60000, "ETH": 3000, "SOL": 100},
        )
        assert ctx["classified_bias"] == "neutral"
        assert ctx["btc_price"] == 60000
        assert ctx["eth_price"] == 3000
        assert ctx["symbols_with_data"] == 3

    def test_build_global_context_risk_on(self):
        from llm.global_brain import build_global_context
        ctx = build_global_context(
            btc_price=60000,
            btc_1h_change=2.0,
            btc_24h_change=5.0,  # BTC up > 3%
            eth_price=3000,
            last_prices={"BTC": 60000},
            funding_rates={"BTC": 0.001, "ETH": 0.002},  # positive funding
        )
        assert ctx["classified_bias"] == "risk_on"

    def test_build_global_context_risk_off(self):
        from llm.global_brain import build_global_context
        ctx = build_global_context(
            btc_price=60000,
            btc_1h_change=-2.0,
            btc_24h_change=-5.0,  # BTC down > 3%
            eth_price=3000,
            last_prices={"BTC": 60000},
            funding_rates={"BTC": -0.001, "ETH": -0.002},  # negative funding
        )
        assert ctx["classified_bias"] == "risk_off"

    def test_apply_global_bias_risk_off_reduces(self):
        from llm.global_brain import apply_global_bias
        result = apply_global_bias("risk_off", base_size_multiplier=1.0, max_positions=6)
        assert result["size_multiplier"] == 0.6
        assert result["max_positions"] == 4  # 6 - 2

    def test_apply_global_bias_risk_on_increases(self):
        from llm.global_brain import apply_global_bias
        result = apply_global_bias("risk_on", base_size_multiplier=1.0, max_positions=6)
        assert result["size_multiplier"] == 1.2
        assert result["max_positions"] == 6


# ── Portfolio Brain ──────────────────────────────────────────

class TestPortfolioBrain:
    def test_empty_portfolio(self):
        from llm.portfolio_brain import build_portfolio_snapshot
        pos_mgr = MagicMock()
        pos_mgr.get_open_positions.return_value = {}
        snap = build_portfolio_snapshot(pos_mgr, {}, 10000)
        assert snap["total_positions"] == 0
        assert snap["total_leverage"] == 0.0

    def test_portfolio_with_positions(self):
        from llm.portfolio_brain import build_portfolio_snapshot
        pos_mgr = MagicMock()
        mock_pos = MagicMock()
        mock_pos.side = "LONG"
        mock_pos.qty = 1.0
        mock_pos.entry = 60000
        mock_pos.leverage = 5.0
        mock_pos.sl = 58000
        mock_pos.state = "OPEN"
        pos_mgr.get_open_positions.return_value = {"BTC": mock_pos}

        snap = build_portfolio_snapshot(
            pos_mgr, {"BTC": 61000}, equity=10000
        )
        assert snap["total_positions"] == 1
        assert snap["long_count"] == 1
        assert snap["short_count"] == 0
        assert snap["total_leverage"] > 0
        assert len(snap["positions"]) == 1

    def test_correlation_guard(self):
        from llm.portfolio_brain import get_correlation_guard
        pos1 = MagicMock()
        pos1.side = "LONG"
        pos1.state = "OPEN"
        pos2 = MagicMock()
        pos2.side = "LONG"
        pos2.state = "OPEN"
        pos3 = MagicMock()
        pos3.side = "SHORT"
        pos3.state = "OPEN"

        positions = {"BTC": pos1, "ETH": pos2, "SOL": pos3}
        allowed, reason = get_correlation_guard(positions, "LONG", max_same_direction=2)
        assert not allowed
        assert "Too many" in reason


# ── Self-Tuning Risk ────────────────────────────────────────

class TestSelfTuningRisk:
    def test_telemetry_update(self):
        from risk.self_tuning import RiskTelemetry
        tel = RiskTelemetry()
        tel.update(equity=10000, daily_pnl=100)
        assert tel.current_equity == 10000
        assert tel.peak_equity == 10000
        assert tel.consecutive_loss_days == 0
        assert len(tel.daily_pnls) == 1

    def test_telemetry_drawdown(self):
        from risk.self_tuning import RiskTelemetry
        tel = RiskTelemetry()
        tel.update(equity=10000, daily_pnl=100)
        tel.update(equity=9000, daily_pnl=-1000)
        assert tel.current_drawdown_pct == pytest.approx(10.0)
        assert tel.consecutive_loss_days == 1

    def test_evaluate_conservative_on_drawdown(self):
        from risk import self_tuning
        # Save and restore global state
        old_tel = self_tuning._telemetry
        old_profile = self_tuning._active_profile
        try:
            self_tuning._telemetry = self_tuning.RiskTelemetry()
            self_tuning._active_profile = "normal"
            self_tuning._telemetry.update(equity=10000, daily_pnl=100)
            self_tuning._telemetry.update(equity=9100, daily_pnl=-900)  # 9% DD
            result = self_tuning.evaluate_and_adjust()
            assert result == "conservative"
        finally:
            self_tuning._telemetry = old_tel
            self_tuning._active_profile = old_profile

    def test_dynamic_leverage_cap(self):
        from risk import self_tuning
        old_tel = self_tuning._telemetry
        try:
            self_tuning._telemetry = self_tuning.RiskTelemetry()
            self_tuning._telemetry.peak_equity = 10000
            self_tuning._telemetry.current_equity = 9400
            self_tuning._telemetry.current_drawdown_pct = 6.0  # 5-8% range
            cap = self_tuning.get_dynamic_leverage_cap(25.0)
            assert cap == 15.0  # 25 * 0.6
        finally:
            self_tuning._telemetry = old_tel

    def test_profile_params(self):
        from risk.self_tuning import get_profile_params, RISK_PROFILES
        params = get_profile_params()
        assert "max_leverage" in params
        assert "max_positions" in params
        assert "daily_loss_limit_pct" in params


# ── RL Buffer ───────────────────────────────────────────────

class TestRLBuffer:
    def test_append_and_load_roundtrip(self, tmp_path):
        """Test that transitions written to the buffer can be loaded back."""
        buf_file = str(tmp_path / "transitions.jsonl")
        with patch("rl.buffer._BUFFER_FILE", buf_file), \
             patch("rl.buffer._RL_DIR", str(tmp_path)):
            from rl.buffer import append_transition, load_buffer

            append_transition(
                state={"symbol": "BTC", "regime": "trend", "confidence": 0.8},
                action={"llm_mode": "VETO_ONLY", "leverage": 5.0},
                reward=0.5,
                metadata={"trigger": "PRE_TRADE", "outcome": "WIN"},
            )
            append_transition(
                state={"symbol": "ETH", "regime": "range", "confidence": 0.6},
                action={"llm_mode": "SIZING", "leverage": 3.0},
                reward=-0.3,
                metadata={"trigger": "PERIODIC", "outcome": "LOSS"},
            )

            transitions = load_buffer(buf_file)
            assert len(transitions) == 2
            assert transitions[0]["state"]["symbol"] == "BTC"
            assert transitions[0]["reward"] == 0.5
            assert transitions[1]["state"]["symbol"] == "ETH"
            assert transitions[1]["reward"] == -0.3

    def test_buffer_stats(self, tmp_path):
        buf_file = str(tmp_path / "transitions.jsonl")
        with patch("rl.buffer._BUFFER_FILE", buf_file), \
             patch("rl.buffer._RL_DIR", str(tmp_path)):
            from rl.buffer import append_transition, get_buffer_stats, load_buffer

            for i in range(5):
                append_transition(
                    state={"symbol": "BTC", "regime": "trend"},
                    action={"leverage": 5.0},
                    reward=0.2 if i % 2 == 0 else -0.1,
                )

            stats = get_buffer_stats(load_buffer(buf_file))
            assert stats["total"] == 5
            assert stats["win_rate"] == 0.6  # 3 out of 5


# ── RL Apply Policy ─────────────────────────────────────────

class TestRLApplyPolicy:
    def test_disabled_returns_1(self):
        from rl.apply_policy import get_combined_rl_multiplier
        with patch("rl.apply_policy.ENABLE_RL_POLICY", False):
            assert get_combined_rl_multiplier("BTC", "trend") == 1.0

    def test_enabled_with_policy(self):
        policy = {
            "regime_multipliers": {"trend": 1.15, "range": 0.8},
            "symbol_risk_caps": {"BTC": 1.1},
            "trigger_adjustments": {},
        }

        import rl.apply_policy as ap_mod
        old_enable = ap_mod.ENABLE_RL_POLICY
        try:
            ap_mod.ENABLE_RL_POLICY = True
            # Patch load_policy to return our test policy (avoids default path issue)
            with patch("rl.apply_policy.load_policy", return_value=policy):
                mult = ap_mod.get_combined_rl_multiplier("BTC", "trend")
                # 1.15 * 1.1 = 1.265, clamped to max 1.20
                assert mult == pytest.approx(1.20)
        finally:
            ap_mod.ENABLE_RL_POLICY = old_enable

    def test_clamp_bounds(self):
        from rl.apply_policy import _clamp
        assert _clamp(2.0) == 1.20  # Max increase
        assert _clamp(0.1) == 0.50  # Min decrease
        assert _clamp(1.0) == 1.0   # No change


# ── Autonomy Mode Constraints ──────────────────────────────

class TestAutonomyConstraints:
    def _make_decision(self, action="proceed", confidence=0.7, size_mult=1.0):
        from llm.decision_types import LLMDecision, StrategyWeights
        return LLMDecision(
            action=action,
            confidence=confidence,
            regime="trend",
            strategy_weights=StrategyWeights(),
            memory_update=None,
            notes="test",
            size_multiplier=size_mult,
        )

    def test_veto_only_blocks_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.9)
        result, overrides = _apply_mode_constraints(d, LLMMode.VETO_ONLY)
        assert result.action == "flat"
        assert "flip_to_flat" in overrides

    def test_sizing_blocks_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.9, size_mult=1.5)
        result, overrides = _apply_mode_constraints(d, LLMMode.SIZING)
        assert result.action == "flat"
        assert result.size_multiplier == 1.5  # Sizing keeps size_mult

    def test_direction_allows_high_conf_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.70)
        result, overrides = _apply_mode_constraints(d, LLMMode.DIRECTION)
        assert result.action == "flip"  # Allowed: 0.70 >= 0.65

    def test_direction_blocks_low_conf_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.50)
        result, overrides = _apply_mode_constraints(d, LLMMode.DIRECTION)
        assert result.action == "flat"  # Blocked: 0.50 < 0.65

    def test_full_allows_medium_conf_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.60)
        result, overrides = _apply_mode_constraints(d, LLMMode.FULL)
        assert result.action == "flip"  # Allowed: 0.60 >= 0.55

    def test_full_blocks_very_low_conf_flip(self):
        from llm.decision_engine import _apply_mode_constraints
        from llm.autonomy import LLMMode
        d = self._make_decision(action="flip", confidence=0.40)
        result, overrides = _apply_mode_constraints(d, LLMMode.FULL)
        assert result.action == "flat"  # Blocked: 0.40 < 0.55


# ── Snapshot Builder Serialization ──────────────────────────

class TestSnapshotGlobalBrainSerialization:
    def test_global_bias_in_compact(self):
        """Verify that global_bias appears in compact snapshot when not neutral."""
        from llm.snapshot_builder import _to_compact_dict
        from llm.decision_types import (
            LLMInputSnapshot,
            MarketSnapshot as LLMMarketSnapshot,
            GlobalContext as LLMGlobalContext,
        )

        global_ctx = LLMGlobalContext(
            timestamp=int(time.time() * 1000),
            btc_price=60000,
            btc_change_1h_pct=1.0,
            btc_change_24h_pct=5.0,
            eth_btc_ratio=0.05,
            total_open_positions=1,
            daily_pnl=50,
            equity=10000,
            circuit_breaker_active=False,
        )
        global_ctx.extra = {
            "global_bias": "risk_on",
            "net_funding": 0.001,
            "portfolio_snapshot": {
                "total_positions": 2,
                "total_leverage": 3.5,
                "net_exposure_pct": 15.0,
                "concentration_pct": 60.0,
            },
            "risk_profile": "Balanced defaults. Standard operation.",
            "dynamic_leverage_cap": 20.0,
        }

        snapshot = LLMInputSnapshot(
            markets=[],
            global_context=global_ctx,
            trigger_reason="test",
            trigger_context="",
        )

        compact = _to_compact_dict(snapshot)
        assert compact["g"]["gbias"] == "risk_on"
        assert compact["g"]["nfr"] == 0.001
        assert compact["g"]["pf"]["n"] == 2
        assert compact["g"]["pf"]["lv"] == 3.5
        assert "rprof" in compact["g"]
        assert compact["g"]["dlcap"] == 20.0
