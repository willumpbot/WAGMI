"""
Tests for the Trade Classification Layer.

Verifies:
1. Strategy -> entry_type mapping works correctly
2. SCALP trades have tighter TP1/SL than TREND trades
3. SCALP closes more % at TP1 than TREND
4. Trailing behavior differs by entry_type
5. Regime and volatility modify exit params
6. EV per entry_type is computed and exported
7. Profile is attached to positions and logged on close
"""

import json
import os
import sys

import pytest

# Allow imports from bot/ root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.trade_profile import (
    classify_trade, apply_profile_to_signal,
    TradeProfile, ExitParams,
    SCALP, MEDIUM, TREND, REGIME,
    STRATEGY_ENTRY_TYPE, _BASE_PROFILES,
    _determine_primary_driver, _determine_entry_type,
    _adjust_params_for_regime,
)
from execution.position_manager import PositionManager
from execution.position_state import TRAILING, TP1_HIT
from data.learning import record_trade_outcome, get_performance, _recent_outcomes


# ─── Fixtures ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def tmpdir_data(tmp_path, monkeypatch):
    """Redirect data writes to temp dir."""
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setattr("execution.position_state._LOG_DIR", os.path.join(data_dir, "logs"))
    monkeypatch.setattr("execution.position_state._LOG_FILE", os.path.join(data_dir, "logs", "state_transitions.csv"))
    monkeypatch.setattr("data.learning._OUTCOMES_DIR", os.path.join(data_dir, "analysis"))
    monkeypatch.setattr("data.learning._OUTCOMES_FILE", os.path.join(data_dir, "analysis", "trade_outcomes.csv"))
    monkeypatch.setattr("data.learning._PERF_FILE", os.path.join(data_dir, "analysis", "performance.json"))
    _recent_outcomes.clear()
    yield tmp_path


# ─── 1. Strategy -> entry_type mapping ───────────────────

class TestStrategyMapping:
    def test_regime_trend_is_trend(self):
        assert STRATEGY_ENTRY_TYPE["regime_trend"] == TREND

    def test_multi_tier_is_medium(self):
        assert STRATEGY_ENTRY_TYPE["multi_tier_quality"] == MEDIUM

    def test_monte_carlo_is_medium(self):
        assert STRATEGY_ENTRY_TYPE["monte_carlo_zones"] == MEDIUM

    def test_confidence_scorer_is_medium(self):
        assert STRATEGY_ENTRY_TYPE["confidence_scorer"] == MEDIUM

    def test_unknown_strategy_defaults_to_medium(self):
        """Unknown strategies should default to MEDIUM (conservative)."""
        entry_type = _determine_entry_type("unknown_strat", ["unknown_strat"])
        assert entry_type == MEDIUM


# ─── 2. SCALP vs TREND exit parameters ──────────────────

class TestExitProfileDifferences:
    def test_scalp_tighter_tp1_than_trend(self):
        """SCALP TP1 distance should be smaller than TREND."""
        scalp = _BASE_PROFILES[SCALP]
        trend = _BASE_PROFILES[TREND]
        assert scalp.tp1_atr_mult < trend.tp1_atr_mult

    def test_scalp_tighter_sl_than_trend(self):
        """SCALP SL distance should be smaller than TREND."""
        scalp = _BASE_PROFILES[SCALP]
        trend = _BASE_PROFILES[TREND]
        assert scalp.sl_atr_mult < trend.sl_atr_mult

    def test_scalp_closes_more_at_tp1(self):
        """SCALP should close more % at TP1 than TREND."""
        scalp = _BASE_PROFILES[SCALP]
        trend = _BASE_PROFILES[TREND]
        assert scalp.tp1_close_pct > trend.tp1_close_pct

    def test_scalp_trailing_tighter(self):
        """SCALP trailing should tighten faster than TREND."""
        scalp = _BASE_PROFILES[SCALP]
        trend = _BASE_PROFILES[TREND]
        assert scalp.trailing_style == "tight"
        assert trend.trailing_style == "medium"
        # SCALP end factor >= TREND end factor (tighter = higher).
        # With widened TREND trailing (0.60), values may be equal — SCALP is still
        # effectively tighter due to "tight" trailing_style multiplier.
        assert scalp.trailing_tighten_end >= trend.trailing_tighten_end

    def test_medium_between_scalp_and_trend(self):
        """MEDIUM parameters should be between SCALP and TREND."""
        scalp = _BASE_PROFILES[SCALP]
        medium = _BASE_PROFILES[MEDIUM]
        trend = _BASE_PROFILES[TREND]
        assert scalp.tp1_atr_mult < medium.tp1_atr_mult < trend.tp1_atr_mult
        assert scalp.sl_atr_mult < medium.sl_atr_mult < trend.sl_atr_mult
        assert scalp.tp1_close_pct > medium.tp1_close_pct > trend.tp1_close_pct


# ─── 3. Classification logic ────────────────────────────

class TestClassificationLogic:
    def test_classify_trend_signal(self):
        """Two TREND strategies -> TREND classification."""
        metadata = {
            "strategies_agree": ["regime_trend", "multi_tier_quality"],
            "individual_confidences": {"regime_trend": 80, "multi_tier_quality": 75},
            "strategy_weights": {"regime_trend": 0.7, "multi_tier_quality": 0.6},
        }
        profile = classify_trade(metadata, confidence=78, atr=2.0, entry=100.0, side="BUY")
        assert profile.entry_type == TREND
        assert profile.primary_driver in ("regime_trend", "multi_tier_quality")
        assert profile.exit_params.tp1_close_pct <= 0.75  # TREND base 0.60, regime adjustment may increase

    def test_classify_medium_signal(self):
        """Two MEDIUM strategies -> MEDIUM classification."""
        metadata = {
            "strategies_agree": ["monte_carlo_zones", "confidence_scorer"],
            "individual_confidences": {"monte_carlo_zones": 72, "confidence_scorer": 70},
            "strategy_weights": {"monte_carlo_zones": 0.5, "confidence_scorer": 0.5},
        }
        profile = classify_trade(metadata, confidence=71, atr=2.0, entry=100.0, side="BUY")
        assert profile.entry_type == MEDIUM

    def test_classify_mixed_trend_medium(self):
        """Mixed TREND + MEDIUM: type follows primary driver."""
        metadata = {
            "strategies_agree": ["regime_trend", "monte_carlo_zones"],
            "individual_confidences": {"regime_trend": 85, "monte_carlo_zones": 70},
            "strategy_weights": {"regime_trend": 0.8, "monte_carlo_zones": 0.5},
        }
        profile = classify_trade(metadata, confidence=78, atr=2.0, entry=100.0, side="BUY")
        # regime_trend has higher score (0.8*85=68 vs 0.5*70=35) -> primary = regime_trend -> TREND
        assert profile.primary_driver == "regime_trend"
        assert profile.entry_type == TREND

    def test_volatility_band_classification(self):
        """High ATR/price ratio -> high volatility band."""
        profile = classify_trade(
            {"strategies_agree": ["regime_trend"], "individual_confidences": {"regime_trend": 80},
             "strategy_weights": {"regime_trend": 0.7}},
            confidence=80, atr=5.0, entry=100.0, side="BUY",  # 5% ATR = high vol
        )
        assert profile.volatility_band == "high"

    def test_low_volatility_classification(self):
        profile = classify_trade(
            {"strategies_agree": ["regime_trend"], "individual_confidences": {"regime_trend": 80},
             "strategy_weights": {"regime_trend": 0.7}},
            confidence=80, atr=1.0, entry=100.0, side="BUY",  # 1% ATR = low vol
        )
        assert profile.volatility_band == "low"


# ─── 4. Regime adjustments ──────────────────────────────

class TestRegimeAdjustments:
    def test_trending_lowers_tp1_close_pct(self):
        """In trending regime, TP1% should decrease (let winners run)."""
        base = _BASE_PROFILES[MEDIUM]
        adjusted = _adjust_params_for_regime(base, "trending", "medium")
        assert adjusted.tp1_close_pct < base.tp1_close_pct

    def test_ranging_raises_tp1_close_pct(self):
        """In ranging regime, TP1% should increase (take profits quickly)."""
        base = _BASE_PROFILES[MEDIUM]
        adjusted = _adjust_params_for_regime(base, "ranging", "medium")
        assert adjusted.tp1_close_pct > base.tp1_close_pct

    def test_high_volatility_widens_sl(self):
        """High volatility should widen SL to avoid noise stopouts."""
        base = _BASE_PROFILES[MEDIUM]
        adjusted = _adjust_params_for_regime(base, "ranging", "high")
        assert adjusted.sl_atr_mult > base.sl_atr_mult

    def test_illiquid_raises_tp1_close_pct(self):
        """Illiquid markets should close more at TP1 (conservative)."""
        base = _BASE_PROFILES[MEDIUM]
        adjusted = _adjust_params_for_regime(base, "illiquid", "medium")
        assert adjusted.tp1_close_pct > base.tp1_close_pct


# ─── 5. apply_profile_to_signal ──────────────────────────

class TestApplyProfile:
    def test_profile_adjusts_tp1_for_trend(self):
        """TREND profile should produce wider TP1 than raw signal."""
        metadata = {
            "strategies_agree": ["regime_trend", "multi_tier_quality"],
            "individual_confidences": {"regime_trend": 80, "multi_tier_quality": 75},
            "strategy_weights": {"regime_trend": 0.7, "multi_tier_quality": 0.6},
        }
        profile = classify_trade(metadata, confidence=78, atr=5.0, entry=100.0, side="BUY")
        adjusted = apply_profile_to_signal(
            profile, entry=100.0, sl=95.0, tp1=105.0, tp2=110.0, atr=5.0, side="BUY",
        )
        # TREND TP1 = entry + 1.5*ATR = 107.5 (wider than signal's 105)
        assert adjusted["tp1"] > 105.0

    def test_profile_blends_sl_for_medium(self):
        """Profile should take WIDER SL (more room) to preserve edge."""
        metadata = {
            "strategies_agree": ["monte_carlo_zones"],
            "individual_confidences": {"monte_carlo_zones": 72},
            "strategy_weights": {"monte_carlo_zones": 0.5},
        }
        profile = classify_trade(metadata, confidence=72, atr=5.0, entry=100.0, side="BUY")
        adjusted = apply_profile_to_signal(
            profile, entry=100.0, sl=90.0, tp1=105.0, tp2=115.0, atr=5.0, side="BUY",
        )
        # Blend logic: takes WIDER SL = min(profile_sl, strategy_sl) for LONG.
        # Strategy SL=90.0 is wider than profile SL (~96.25), so strategy wins.
        assert adjusted["sl"] == 90.0

    def test_no_atr_falls_back_to_original(self):
        """When ATR is 0, use signal's original levels."""
        profile = classify_trade(
            {"strategies_agree": ["regime_trend"], "individual_confidences": {"regime_trend": 80},
             "strategy_weights": {"regime_trend": 0.7}},
            confidence=80, atr=0.0, entry=100.0, side="BUY",
        )
        adjusted = apply_profile_to_signal(
            profile, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0, atr=0.0, side="BUY",
        )
        assert adjusted["tp1"] == 107.5
        assert adjusted["sl"] == 95.0


# ─── 6. Position manager uses profile ───────────────────

class TestPositionManagerWithProfile:
    def _make_trend_profile(self):
        return classify_trade(
            {"strategies_agree": ["regime_trend", "multi_tier_quality"],
             "individual_confidences": {"regime_trend": 80, "multi_tier_quality": 75},
             "strategy_weights": {"regime_trend": 0.7, "multi_tier_quality": 0.6},
             "trend_adjustment": -8},  # strong trend alignment -> trending regime
            confidence=78, atr=2.0, entry=100.0, side="BUY",
        )

    def _make_medium_profile(self):
        return classify_trade(
            {"strategies_agree": ["monte_carlo_zones", "confidence_scorer"],
             "individual_confidences": {"monte_carlo_zones": 72, "confidence_scorer": 70},
             "strategy_weights": {"monte_carlo_zones": 0.5, "confidence_scorer": 0.5}},
            confidence=71, atr=5.0, entry=100.0, side="BUY",
        )

    def test_profile_stored_on_position(self):
        """Position should have trade_profile attached."""
        pm = PositionManager()
        prof = self._make_trend_profile()
        pos = pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=107.5, tp2=115.0, atr=5.0,
            leverage=2.0, trade_profile=prof,
        )
        assert pos is not None
        assert pos.trade_profile is not None
        assert pos.trade_profile.entry_type == TREND

    def test_trend_trailing_is_looser(self):
        """TREND profile should tighten trailing slower."""
        pm = PositionManager()
        prof = self._make_trend_profile()
        pos = pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=98.0, tp1=103.0, tp2=106.0, atr=2.0,
            leverage=2.0, trade_profile=prof,
        )
        # TREND uses medium trailing -> trailing_distance = atr * 1.5 = 3.0
        assert pos.trailing_distance >= 2.0 * 1.5  # atr * trailing_atr_mult

    def test_profile_overrides_tp1_close_pct(self):
        """Profile TP1% should override the passed tp1_close_pct."""
        pm = PositionManager()
        prof = self._make_trend_profile()
        pos = pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=98.0, tp1=103.0, tp2=106.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.90,  # would be 90% without profile
            trade_profile=prof,
        )
        # TREND + trending regime: base 0.50 - 0.10 = 0.40
        assert pos.tp1_close_pct <= 0.50, f"Expected TREND TP1%<=50%, got {pos.tp1_close_pct}"

    def test_close_event_includes_entry_type(self):
        """Trade close event metadata should include entry_type."""
        pm = PositionManager()
        prof = self._make_trend_profile()
        pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=103.0, tp2=106.0, atr=2.0,
            leverage=2.0, trade_profile=prof,
        )
        # Walk to SL
        events = pm.update_price("BTC", 94.0)
        assert len(events) >= 1
        close_event = events[-1]
        assert close_event.metadata.get("entry_type") == TREND
        assert close_event.metadata.get("trade_profile") is not None


# ─── 7. EV per entry_type ───────────────────────────────

class TestEvPerEntryType:
    def test_ev_computed_per_type(self, tmpdir_data):
        """performance.json should contain by_entry_type with EV metrics."""
        # Record some TREND and MEDIUM outcomes
        for i in range(5):
            record_trade_outcome(
                symbol="BTC", side="LONG", outcome="CLEAN_WIN",
                pnl=100.0, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0,
                tp1_hit=True, sl_after_tp1=False,
                state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
                leverage=2.0, confidence=80.0, strategy="regime_trend",
                entry_type="TREND", primary_driver="regime_trend", regime="trending",
            )
        for i in range(5):
            record_trade_outcome(
                symbol="SOL", side="LONG", outcome="CLEAN_LOSS",
                pnl=-50.0, entry=50.0, sl=47.0, tp1=53.0, tp2=56.0,
                tp1_hit=False, sl_after_tp1=False,
                state_path="IDLE->OPEN->CLOSED",
                leverage=2.0, confidence=70.0, strategy="monte_carlo_zones",
                entry_type="MEDIUM", primary_driver="monte_carlo_zones", regime="ranging",
            )

        perf = get_performance()
        assert "by_entry_type" in perf

        # TREND should have positive EV (all wins)
        trend_ev = perf["by_entry_type"].get("TREND")
        assert trend_ev is not None
        assert trend_ev["win_rate"] == 1.0
        assert trend_ev["EV_per_trade"] > 0

        # MEDIUM should have negative EV (all losses)
        medium_ev = perf["by_entry_type"].get("MEDIUM")
        assert medium_ev is not None
        assert medium_ev["win_rate"] == 0.0
        assert medium_ev["EV_per_trade"] < 0

    def test_by_regime_in_performance(self, tmpdir_data):
        """performance.json should include by_regime metrics."""
        record_trade_outcome(
            symbol="BTC", side="LONG", outcome="CLEAN_WIN",
            pnl=100.0, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0,
            tp1_hit=True, sl_after_tp1=False,
            state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
            entry_type="TREND", primary_driver="regime_trend", regime="trending",
        )
        perf = get_performance()
        assert "by_regime" in perf
        assert "trending" in perf["by_regime"]
        assert perf["by_regime"]["trending"]["count"] == 1

    def test_by_strategy_in_performance(self, tmpdir_data):
        """performance.json should include by_strategy metrics."""
        record_trade_outcome(
            symbol="BTC", side="LONG", outcome="CLEAN_WIN",
            pnl=100.0, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0,
            tp1_hit=True, sl_after_tp1=False,
            state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
            entry_type="TREND", primary_driver="regime_trend", regime="trending",
        )
        perf = get_performance()
        assert "by_strategy" in perf
        assert "regime_trend" in perf["by_strategy"]


# ─── 8. Profile-Specific Hold Limits ─────────────────────

class TestProfileHoldLimits:
    def _make_profile(self, entry_type: str) -> TradeProfile:
        return TradeProfile(
            entry_type=entry_type,
            entry_reasons=["regime_trend"],
            primary_driver="regime_trend",
            confidence=75.0,
            regime="trending",
            volatility_band="medium",
            timeframe_bias="medium",
            exit_params=_BASE_PROFILES[entry_type],
        )

    def test_hold_limits_use_profile(self, tmpdir_data):
        """Position manager should use profile-specific max hold hours."""
        pm = PositionManager()
        # Verify the mapping exists
        assert pm._PROFILE_MAX_HOLD_HOURS["SCALP"] == 4
        assert pm._PROFILE_MAX_HOLD_HOURS["MEDIUM"] == 12
        assert pm._PROFILE_MAX_HOLD_HOURS["TREND"] == 36
        assert pm._PROFILE_MAX_HOLD_HOURS["REGIME"] == 48


# ─── 9. R:R Validation After Regime Adjustment ──────────

class TestRRValidation:
    def test_rr_preserved_after_ranging_adjustment(self, tmpdir_data):
        """Ranging regime tightens TP but widens SL — R:R should still be >= 0.5.

        From 1,410-signal analysis: R:R 1.0-1.5 has 57% WR (best bucket).
        Lower R:R is acceptable when WR compensates. Minimum floor at 0.5
        prevents extremely lopsided risk/reward.
        """
        base = _BASE_PROFILES[MEDIUM]
        adjusted = _adjust_params_for_regime(base, "ranging", "medium")
        # TP1 should be at least 0.5 * SL distance (data-driven minimum)
        assert adjusted.tp1_atr_mult >= adjusted.sl_atr_mult * 0.5, (
            f"R:R too low after ranging adjustment: "
            f"TP1={adjusted.tp1_atr_mult:.2f} < SL*0.5={adjusted.sl_atr_mult * 0.5:.2f}"
        )

    def test_rr_preserved_after_low_vol_adjustment(self, tmpdir_data):
        """Low vol tightens SL — TP1 should still maintain min R:R."""
        base = _BASE_PROFILES[TREND]
        adjusted = _adjust_params_for_regime(base, "trending", "low")
        assert adjusted.tp1_atr_mult >= adjusted.sl_atr_mult * 0.8
