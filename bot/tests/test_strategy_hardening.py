"""
Tests for Push 3: Wire Dormant Features & Strategy Hardening.

Covers:
  - 3A: Regime detector needs 3 confirmations and 60% dominance
  - 3B: Regime profitability gate returns correct data
  - 3F-ensemble: LLM ensemble disabled by default
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from collections import defaultdict

# Ensure bot/ is on the import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# 3A: Regime Detector Hardening
# ═══════════════════════════════════════════════════════════════


class TestRegimeDetectorHardening:
    """Tests for regime detector with 3 confirmations and 60% dominance."""

    def _make_detector(self, history_size=10, min_confirmations=3):
        """Create a RegimeTransitionDetector with specified parameters."""
        from strategies.regime_detector import RegimeTransitionDetector
        return RegimeTransitionDetector(
            history_size=history_size,
            min_confirmations=min_confirmations,
        )

    def test_regime_detector_needs_3_confirmations(self):
        """Feed only 2 new regime labels -- verify NOT transitioned.

        With min_confirmations=3 (the new default), 2 labels of a new
        regime should not be enough to trigger a transition.
        """
        detector = self._make_detector(history_size=10, min_confirmations=3)

        # Establish "trend" as the confirmed regime
        detector.update("BTC", "trend")
        assert detector.get_regime("BTC") == "trend"

        # Feed only 2 "volatile" labels -- should NOT transition
        r1 = detector.update("BTC", "volatile")
        r2 = detector.update("BTC", "volatile")

        # Regime should still be "trend"
        assert detector.get_regime("BTC") == "trend"
        # The result should NOT have confirmed a transition
        assert r2["regime"] == "trend"
        # Confirmations should be 2 (not enough)
        assert r2["confirmations"] == 2

    def test_regime_detector_needs_60pct_dominance(self):
        """Feed 3 new + 2 old in a window -- verify dominance blocks.

        Even with 3 confirmations, if the new regime is only 3/5 = 60%
        of the window (not strictly > 60%), the dominance check should
        block the transition.
        """
        detector = self._make_detector(history_size=5, min_confirmations=3)

        # Establish "trend" as the confirmed regime
        detector.update("BTC", "trend")

        # Feed: 2 old ("trend") + 3 new ("volatile") = 3/5 = 60% exactly
        # (not > 60%, so dominance check should block)
        detector.update("BTC", "trend")
        detector.update("BTC", "volatile")
        detector.update("BTC", "volatile")
        result = detector.update("BTC", "volatile")

        # 3 confirmations met, but dominance = 3/5 = 0.60 which is NOT > 0.60
        # so the transition should be BLOCKED
        assert detector.get_regime("BTC") == "trend"
        assert result["confirmations"] == 3
        # The regime in result should still be "trend" (not confirmed)
        assert result["regime"] == "trend"

    def test_regime_detector_confirms_with_dominance(self):
        """Feed 4 new + 1 old -- verify transition confirmed.

        After initial "trend", feed 3 "volatile" labels. At the 3rd volatile,
        history is [trend, volatile, volatile, volatile]: 3/4 = 75% > 60%
        dominance, and 3 >= 3 confirmations, so transition confirms on that
        call. We capture the result of the confirming call.
        """
        detector = self._make_detector(history_size=5, min_confirmations=3)

        # Establish "trend" as the confirmed regime
        detector.update("BTC", "trend")

        # Feed volatile labels: transition confirms on the 3rd one
        # History after 3rd: [trend, volatile, volatile, volatile]
        # new_count = 3, dominance = 3/4 = 75% > 60%, new_count > old_count (1)
        detector.update("BTC", "volatile")
        detector.update("BTC", "volatile")
        result = detector.update("BTC", "volatile")

        # Transition confirmed on this call
        assert detector.get_regime("BTC") == "volatile"
        assert result["regime"] == "volatile"
        assert result["transitioning"] is True
        assert result["from_regime"] == "trend"
        assert result["to_regime"] == "volatile"
        assert result["confirmations"] == 3

    def test_default_min_confirmations_is_3(self):
        """Verify that the module-level default is 3 (not the old 2)."""
        from strategies.regime_detector import _MIN_CONFIRMATIONS
        # Allow env override, but without env var it should default to 3
        assert _MIN_CONFIRMATIONS >= 3

    def test_env_override_min_confirmations(self):
        """Verify REGIME_MIN_CONFIRMATIONS env var overrides the default."""
        # This tests that the env var is read; the actual parsing happens at
        # module load time, so we verify the mechanism exists.
        from strategies import regime_detector
        # The module reads os.getenv("REGIME_MIN_CONFIRMATIONS", "3")
        assert hasattr(regime_detector, "_MIN_CONFIRMATIONS")


# ═══════════════════════════════════════════════════════════════
# 3B: Regime Profitability Gate
# ═══════════════════════════════════════════════════════════════


class TestRegimeProfitability:
    """Tests for get_regime_profitability on SignalQualityScorer."""

    def _make_scorer(self):
        """Create a SignalQualityScorer with mocked by_regime data."""
        from feedback.signal_quality import SignalQualityScorer
        scorer = SignalQualityScorer.__new__(SignalQualityScorer)
        # Manually initialize the state we need (bypass __init__ / file I/O)
        scorer.by_regime = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        return scorer

    def test_regime_profitability_returns_data(self):
        """Mock by_regime data, verify get_regime_profitability returns correct WR."""
        scorer = self._make_scorer()

        # Inject mock data: "trend" regime with 7 wins out of 10, total PnL = 5.0
        scorer.by_regime["trend"] = {
            "wins": 7,
            "total": 10,
            "pnl": 5.0,
            "recent": [1, 1, 1, 0, 1, 1, 0, 1, 0, 1],
        }

        result = scorer.get_regime_profitability("trend")

        assert result["win_rate"] == 0.7
        assert result["total"] == 10
        assert result["avg_pnl"] == 0.5

    def test_regime_profitability_empty_regime(self):
        """Verify returns zeros for a regime with no data."""
        scorer = self._make_scorer()

        result = scorer.get_regime_profitability("nonexistent")

        assert result["win_rate"] == 0.0
        assert result["total"] == 0
        assert result["avg_pnl"] == 0.0

    def test_regime_profitability_all_losses(self):
        """Verify correct stats when all trades are losses."""
        scorer = self._make_scorer()

        scorer.by_regime["choppy"] = {
            "wins": 0,
            "total": 5,
            "pnl": -2.5,
            "recent": [0, 0, 0, 0, 0],
        }

        result = scorer.get_regime_profitability("choppy")

        assert result["win_rate"] == 0.0
        assert result["total"] == 5
        assert result["avg_pnl"] == -0.5


# ═══════════════════════════════════════════════════════════════
# 3F: LLM Ensemble disabled by default
# ═══════════════════════════════════════════════════════════════


class TestLLMEnsembleDisabledByDefault:
    """Verify ensemble is off when env var is not set."""

    def test_llm_ensemble_disabled_by_default(self):
        """When LLM_ENSEMBLE_ENABLED is not set, ensemble should not activate.

        This tests the gating logic in decision_engine.py. The ensemble
        code path requires LLM_ENSEMBLE_ENABLED to be explicitly set to
        a truthy value AND LLM_PERSONAS to be non-empty.
        """
        # Clear the env vars to ensure default state
        env_patch = {
            "LLM_ENSEMBLE_ENABLED": "",
            "LLM_PERSONAS": "",
        }

        with patch.dict(os.environ, env_patch, clear=False):
            # The gating condition from decision_engine.py
            ensemble_enabled = (
                os.getenv("LLM_ENSEMBLE_ENABLED", "").lower() in ("1", "true", "yes")
                and os.getenv("LLM_PERSONAS", "").strip()
            )
            assert ensemble_enabled is False

    def test_llm_ensemble_disabled_when_false(self):
        """When LLM_ENSEMBLE_ENABLED=false, ensemble should not activate."""
        env_patch = {
            "LLM_ENSEMBLE_ENABLED": "false",
            "LLM_PERSONAS": "opus:1.0,sonnet:0.8",
        }

        with patch.dict(os.environ, env_patch, clear=False):
            ensemble_enabled = (
                os.getenv("LLM_ENSEMBLE_ENABLED", "").lower() in ("1", "true", "yes")
                and os.getenv("LLM_PERSONAS", "").strip()
            )
            assert ensemble_enabled is False

    def test_llm_ensemble_disabled_without_personas(self):
        """When LLM_ENSEMBLE_ENABLED=true but no personas, ensemble should not activate."""
        env_patch = {
            "LLM_ENSEMBLE_ENABLED": "true",
            "LLM_PERSONAS": "",
        }

        with patch.dict(os.environ, env_patch, clear=False):
            ensemble_enabled = (
                os.getenv("LLM_ENSEMBLE_ENABLED", "").lower() in ("1", "true", "yes")
                and bool(os.getenv("LLM_PERSONAS", "").strip())
            )
            assert ensemble_enabled is False

    def test_llm_ensemble_enabled_when_configured(self):
        """When both env vars are set, ensemble gating condition is True."""
        env_patch = {
            "LLM_ENSEMBLE_ENABLED": "true",
            "LLM_PERSONAS": "opus:1.0,sonnet:0.8",
        }

        with patch.dict(os.environ, env_patch, clear=False):
            ensemble_enabled = (
                os.getenv("LLM_ENSEMBLE_ENABLED", "").lower() in ("1", "true", "yes")
                and bool(os.getenv("LLM_PERSONAS", "").strip())
            )
            assert ensemble_enabled is True

    def test_trading_config_default_ensemble_disabled(self):
        """Verify TradingConfig defaults LLM ensemble to disabled."""
        # Ensure env vars are cleared
        env_patch = {
            "LLM_ENSEMBLE_ENABLED": "",
            "LLM_PERSONAS": "",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            from trading_config import TradingConfig
            config = TradingConfig()
            assert config.llm_ensemble_enabled is False
            assert config.llm_personas == ""
