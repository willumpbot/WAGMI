"""
Tests for Wave 3 feature wiring into multi_strategy_main.py:
  - Survival Pressure: outcome recording and LLM context injection
  - Learning Mode: signal/trade observation, counterfactual, constraints
  - Autonomy Progression: gate evaluation and reporting
  - Uplift Analytics: baseline vs LLM-filtered comparison
  - Adaptive Risk: dynamic risk multiplier based on streak/regime
  - Strategy Pruning: weight adjustments for underperforming strategies
  - Human Copy-Trade Classifier: eligibility gate for copy-tradable signals
  - LLM Self-Performance: rolling accuracy stats injection
  - HTTP Client: shared session with pooling, retries, rate limiting
  - Strategy Discovery: corpus, proposals, research, sandbox lifecycle
"""

import os
import sys
import json
import time
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Survival Pressure ──────────────────────────────────────

class TestSurvivalPressure:
    """Survival pressure tracks outcomes and injects accountability into LLM context."""

    def test_import_public_api(self):
        from llm.survival_pressure import (
            record_trade_outcome,
            get_survival_context_for_llm,
            get_survival_report,
        )
        assert callable(record_trade_outcome)
        assert callable(get_survival_context_for_llm)
        assert callable(get_survival_report)

    def test_record_win_updates_state(self):
        import llm.survival_pressure as sp
        old_state = sp._state
        try:
            sp._state = sp.SurvivalState(started_at=time.time())
            sp.record_trade_outcome(outcome="WIN", pnl=50.0, funding_cost=1.2, equity=10000)
            assert sp._state.total_trades == 1
            assert sp._state.total_wins == 1
            assert sp._state.total_pnl == 50.0
            assert sp._state.total_funding_paid == 1.2
        finally:
            sp._state = old_state

    def test_record_loss_updates_state(self):
        import llm.survival_pressure as sp
        old_state = sp._state
        try:
            sp._state = sp.SurvivalState(started_at=time.time())
            sp.record_trade_outcome(outcome="LOSS", pnl=-30.0, funding_cost=0.5, equity=9970)
            assert sp._state.total_trades == 1
            assert sp._state.total_losses == 1
            assert sp._state.total_pnl == -30.0
        finally:
            sp._state = old_state

    def test_survival_context_returns_string(self):
        import llm.survival_pressure as sp
        old_state = sp._state
        try:
            sp._state = sp.SurvivalState(started_at=time.time())
            ctx = sp.get_survival_context_for_llm()
            assert isinstance(ctx, str)
            assert len(ctx) > 0
        finally:
            sp._state = old_state

    def test_survival_report_returns_dict(self):
        import llm.survival_pressure as sp
        old_state = sp._state
        try:
            sp._state = sp.SurvivalState(started_at=time.time())
            report = sp.get_survival_report()
            assert isinstance(report, dict)
            assert "survival_score" in report
        finally:
            sp._state = old_state

    def test_multiple_outcomes_track_correctly(self):
        import llm.survival_pressure as sp
        old_state = sp._state
        try:
            sp._state = sp.SurvivalState(started_at=time.time())
            sp.record_trade_outcome(outcome="WIN", pnl=20.0)
            sp.record_trade_outcome(outcome="WIN", pnl=30.0)
            sp.record_trade_outcome(outcome="LOSS", pnl=-15.0)
            assert sp._state.total_trades == 3
            assert sp._state.total_wins == 2
            assert sp._state.total_losses == 1
            assert sp._state.total_pnl == pytest.approx(35.0)
        finally:
            sp._state = old_state


# ── Learning Mode ──────────────────────────────────────────

class TestLearningMode:
    """Learning mode tracks signals/trades and constrains LLM during ramp-up."""

    def test_import_public_api(self):
        from llm.learning_mode import (
            is_learning_mode_active,
            get_current_phase,
            record_signal_observed,
            record_trade_observed,
            record_counterfactual,
            apply_learning_constraints,
            get_learning_report,
            LearningPhase,
        )
        assert LearningPhase.ABSORB == 0
        assert LearningPhase.APPRENTICE == 1
        assert LearningPhase.ACTIVE == 2

    def test_fresh_state_is_active(self):
        """Fresh learning state should be in learning mode (not graduated)."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            assert lm.is_learning_mode_active()
            assert lm.get_current_phase() == lm.LearningPhase.ABSORB
        finally:
            lm._state = old_state

    def test_absorb_prevents_veto(self):
        """In ABSORB phase, LLM should not be allowed to veto."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm._state.phase = int(lm.LearningPhase.ABSORB)
            action, size, reason = lm.apply_learning_constraints(
                llm_action="flat",
                llm_confidence=0.9,
                llm_size_multiplier=1.0,
                signal_confidence=80.0,
            )
            # In ABSORB, "flat" (veto) should be overridden to "proceed"
            assert action != "flat"
        finally:
            lm._state = old_state

    def test_absorb_limits_size_adjustment(self):
        """In ABSORB phase, size adjustment should be limited to ±20%."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm._state.phase = int(lm.LearningPhase.ABSORB)
            _, size, _ = lm.apply_learning_constraints(
                llm_action="proceed",
                llm_confidence=0.9,
                llm_size_multiplier=2.0,  # LLM wants 2x
                signal_confidence=80.0,
            )
            # Should be clamped to at most 1.2x in ABSORB
            assert size <= 1.2
        finally:
            lm._state = old_state

    def test_graduated_passes_through(self):
        """After graduation, constraints should not apply."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm._state.graduated = True
            action, size, reason = lm.apply_learning_constraints(
                llm_action="flat",
                llm_confidence=0.9,
                llm_size_multiplier=1.5,
                signal_confidence=80.0,
            )
            assert action == "flat"
            assert size == 1.5
            assert reason == "graduated"
        finally:
            lm._state = old_state

    def test_record_signal_increments(self):
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm.record_signal_observed(
                symbol="BTC", side="LONG", confidence=80.0,
                regime="trending_up", strategies=["regime_trend"], num_agree=2,
            )
            assert lm._state.signals_observed == 1
        finally:
            lm._state = old_state

    def test_record_trade_increments(self):
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm.record_trade_observed(
                symbol="BTC", side="LONG", outcome="WIN", pnl=50.0, confidence=85.0,
            )
            assert lm._state.trades_observed == 1
        finally:
            lm._state = old_state

    def test_counterfactual_tracking(self):
        """Counterfactual: veto + LOSS = correct prediction."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm.record_counterfactual(
                llm_would_have_vetoed=True,
                actual_outcome="LOSS",
                pnl=-25.0,
                symbol="BTC",
            )
            assert lm._state.counterfactual_total == 1
            assert lm._state.counterfactual_correct == 1
        finally:
            lm._state = old_state

    def test_counterfactual_wrong_tracking(self):
        """Counterfactual: veto + WIN = wrong prediction."""
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            lm.record_counterfactual(
                llm_would_have_vetoed=True,
                actual_outcome="WIN",
                pnl=50.0,
                symbol="BTC",
            )
            assert lm._state.counterfactual_total == 1
            assert lm._state.counterfactual_correct == 0
        finally:
            lm._state = old_state

    def test_learning_report_returns_dict(self):
        import llm.learning_mode as lm
        old_state = lm._state
        try:
            lm._state = lm.LearningState()
            report = lm.get_learning_report()
            assert isinstance(report, dict)
            assert "phase" in report
        finally:
            lm._state = old_state


# ── Autonomy Progression ──────────────────────────────────

class TestAutonomyProgression:
    """Progression controller gates mode advancement on measurable metrics."""

    def test_import_public_api(self):
        from llm.progression import evaluate_progression, format_progression_status
        assert callable(evaluate_progression)
        assert callable(format_progression_status)

    def test_evaluate_returns_report_or_none(self):
        """evaluate_progression returns a ProgressionReport or None."""
        from llm.progression import evaluate_progression, ProgressionReport
        from llm.autonomy import LLMMode
        result = evaluate_progression(LLMMode.VETO_ONLY)
        # May return None if no target mode, or a report
        assert result is None or isinstance(result, ProgressionReport)

    def test_progression_report_has_gate_counts(self):
        from llm.progression import evaluate_progression, ProgressionReport
        from llm.autonomy import LLMMode
        result = evaluate_progression(LLMMode.VETO_ONLY)
        if result is not None:
            assert hasattr(result, "passed_count")
            assert hasattr(result, "total_count")
            assert hasattr(result, "all_passed")
            assert result.total_count >= result.passed_count

    def test_format_status_returns_string(self):
        from llm.progression import format_progression_status
        from llm.autonomy import LLMMode
        status = format_progression_status(LLMMode.VETO_ONLY)
        assert isinstance(status, str)


# ── Uplift Analytics ───────────────────────────────────────

class TestUpliftAnalytics:
    """Uplift analytics compares baseline vs LLM-filtered performance."""

    def test_import_public_api(self):
        from llm.uplift_analytics import compute_uplift, format_uplift_report
        assert callable(compute_uplift)
        assert callable(format_uplift_report)

    def test_compute_uplift_returns_dict(self):
        from llm.uplift_analytics import compute_uplift
        result = compute_uplift()
        assert isinstance(result, dict)

    def test_format_uplift_report_returns_string(self):
        from llm.uplift_analytics import compute_uplift, format_uplift_report
        data = compute_uplift()  # Use real output structure
        report = format_uplift_report(data)
        assert isinstance(report, str)


# ── Adaptive Risk ──────────────────────────────────────────

class TestAdaptiveRisk:
    """Adaptive risk adjusts position sizing based on recent streaks and regime."""

    def test_import_and_singleton(self):
        from execution.adaptive_risk import get_adaptive_risk, AdaptiveRiskManager
        mgr = get_adaptive_risk()
        assert isinstance(mgr, AdaptiveRiskManager)

    def test_fresh_manager_returns_1x(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager()
        mult = mgr.get_risk_multiplier()
        assert mult == 1.0

    def test_winning_streak_boosts_risk(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager()
        for _ in range(5):
            mgr.record_outcome(win=True, regime="trending_up")
        mult = mgr.get_risk_multiplier(regime="trending_up")
        assert mult > 1.0

    def test_losing_streak_reduces_risk(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager()
        for _ in range(5):
            mgr.record_outcome(win=False, regime="choppy")
        mult = mgr.get_risk_multiplier(regime="choppy")
        assert mult < 1.0

    def test_risk_clamped_within_bounds(self):
        from execution.adaptive_risk import AdaptiveRiskManager, _MIN_RISK_MULT, _MAX_RISK_MULT
        mgr = AdaptiveRiskManager()
        # Even with extreme inputs, multiplier stays in bounds
        for _ in range(20):
            mgr.record_outcome(win=True, regime="trending_up")
        mult = mgr.get_risk_multiplier(regime="trending_up", symbol_wr=0.95)
        assert mult >= _MIN_RISK_MULT
        assert mult <= _MAX_RISK_MULT

    def test_effective_risk_scales_base(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager(base_risk=0.02)
        eff = mgr.get_effective_risk()
        assert eff == pytest.approx(0.02)  # 1.0x multiplier on fresh

    def test_get_status_returns_dict(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager()
        mgr.record_outcome(win=True)
        mgr.record_outcome(win=False)
        status = mgr.get_status()
        assert "recent_streak" in status
        assert "recent_wr" in status
        assert status["recent_streak"] == "WL"

    def test_regime_wr_tracking(self):
        from execution.adaptive_risk import AdaptiveRiskManager
        mgr = AdaptiveRiskManager()
        for _ in range(10):
            mgr.record_outcome(win=True, regime="trending_up")
        for _ in range(10):
            mgr.record_outcome(win=False, regime="choppy")
        status = mgr.get_status()
        assert "trending_up" in status["regime_data"]
        assert "choppy" in status["regime_data"]
        assert status["regime_data"]["trending_up"] == 1.0
        assert status["regime_data"]["choppy"] == 0.0


# ── Strategy Pruning ───────────────────────────────────────

class TestStrategyPruning:
    """Strategy pruning reduces weights for negative-EV strategies."""

    def test_import_public_api(self):
        from execution.strategy_pruning import evaluate_and_adjust, get_strategy_weight
        assert callable(evaluate_and_adjust)
        assert callable(get_strategy_weight)

    def test_no_data_no_adjustments(self):
        from execution.strategy_pruning import evaluate_and_adjust
        result = evaluate_and_adjust({})
        assert result == []

    def test_insufficient_trades_no_adjustment(self):
        """Strategies with < 50 trades should not be pruned."""
        from execution.strategy_pruning import evaluate_and_adjust
        perf = {
            "by_strategy": {
                "regime_trend": {
                    "count": 30,
                    "win_rate": 0.30,
                    "EV_per_trade": -0.5,
                },
            },
        }
        result = evaluate_and_adjust(perf)
        assert result == []

    def test_negative_ev_high_trades_adjusts(self):
        """Strategy with negative EV and enough trades should get reduced."""
        from execution.strategy_pruning import evaluate_and_adjust
        perf = {
            "by_strategy": {
                "bad_strat": {
                    "count": 60,
                    "win_rate": 0.35,
                    "EV_per_trade": -1.5,
                    "avg_win_R": 1.0,
                    "avg_loss_R": 1.2,
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            weights_path = os.path.join(tmpdir, "weights.json")
            with patch("execution.strategy_pruning._WEIGHTS_FILE", weights_path), \
                 patch("execution.strategy_pruning._DECISIONS_FILE", os.path.join(tmpdir, "decisions.csv")), \
                 patch("execution.strategy_pruning._LOG_DIR", tmpdir):
                result = evaluate_and_adjust(perf)
                assert len(result) >= 1
                adj = result[0]
                assert adj["name"] == "bad_strat"
                assert adj["new_weight"] < adj["old_weight"]

    def test_get_strategy_weight_default(self):
        """Strategies without overrides should return 1.0."""
        from execution.strategy_pruning import get_strategy_weight
        with patch("execution.strategy_pruning.load_weight_overrides", return_value={}):
            assert get_strategy_weight("unknown_strat") == 1.0


# ── Human Copy-Trade Classifier ────────────────────────────

class TestHumanCopyClassifier:
    """Copy-trade classifier gates signals for human copy-trading."""

    def test_import_public_api(self):
        from classification.human_copy_classifier import classify_human_copy_tradable, CopyTradeResult
        assert callable(classify_human_copy_tradable)

    def test_high_quality_signal_eligible(self):
        """High confidence, low leverage, good regime should pass."""
        from classification.human_copy_classifier import classify_human_copy_tradable
        result = classify_human_copy_tradable(
            confidence=92.0,
            regime="trend",
            volatility_band="low",
            entry_type="TREND",
            primary_driver="regime_trend",
            leverage=2.0,
            rr=2.5,
        )
        assert result.eligible
        assert result.score > 0

    def test_low_confidence_rejected(self):
        """Low confidence signal should not be copy-tradable."""
        from classification.human_copy_classifier import classify_human_copy_tradable
        result = classify_human_copy_tradable(
            confidence=55.0,
            regime="choppy",
            volatility_band="high",
            entry_type="counter_trend",
            primary_driver="montecarlo",
            leverage=5.0,
            rr=0.8,
        )
        assert not result.eligible
        assert len(result.reasons) > 0

    def test_circuit_breaker_blocks(self):
        """Active circuit breaker should block copy-trade eligibility."""
        from classification.human_copy_classifier import classify_human_copy_tradable
        result = classify_human_copy_tradable(
            confidence=95.0,
            regime="trending_up",
            volatility_band="normal",
            entry_type="breakout",
            primary_driver="regime_trend",
            leverage=2.0,
            rr=3.0,
            circuit_breaker_active=True,
        )
        assert not result.eligible

    def test_result_has_score(self):
        from classification.human_copy_classifier import CopyTradeResult
        r = CopyTradeResult(eligible=True, score=85.0)
        d = r.to_dict()
        assert d["eligible"] is True
        assert d["score"] == 85.0


# ── LLM Self-Performance ──────────────────────────────────

class TestLLMSelfPerformance:
    """Self-performance provides rolling accuracy stats for LLM self-calibration."""

    def test_import_public_api(self):
        from llm.self_performance import get_compact_stats
        assert callable(get_compact_stats)

    def test_compact_stats_with_no_data(self):
        """Should return empty/default stats when no decisions exist."""
        import llm.self_performance as sp
        with patch.object(sp, "_DECISIONS_PATH", "/nonexistent/path"):
            stats = sp.get_compact_stats()
            assert isinstance(stats, (dict, type(None)))


# ── HTTP Client ────────────────────────────────────────────

class TestHTTPClient:
    """Shared HTTP client with pooling, retries, and rate limiting."""

    def test_import_and_singleton(self):
        from http_client import get_http_client, RateLimitedSession
        client = get_http_client()
        assert isinstance(client, RateLimitedSession)

    def test_singleton_returns_same_instance(self):
        from http_client import get_http_client
        c1 = get_http_client()
        c2 = get_http_client()
        assert c1 is c2

    def test_stats_initial_zero(self):
        from http_client import RateLimitedSession
        client = RateLimitedSession()
        stats = client.get_stats()
        assert stats["requests"] == 0
        assert stats["errors"] == 0
        assert stats["error_rate"] == 0
        client.close()

    def test_session_has_user_agent(self):
        from http_client import RateLimitedSession, _USER_AGENT
        client = RateLimitedSession()
        assert client._session.headers.get("User-Agent") == _USER_AGENT
        client.close()


# ── Strategy Discovery ─────────────────────────────────────

class TestStrategyDiscovery:
    """Strategy discovery lifecycle: corpus -> research -> proposals -> sandbox."""

    def test_import_all_exports(self):
        from llm.strategy_discovery import (
            StrategyProposal,
            ProposalStatus,
            add_observation,
            load_observations,
            get_corpus_summary,
            trim_corpus,
            run_research_cycle,
            build_research_prompt,
            parse_research_output,
            create_proposals_from_research,
            save_proposal,
            load_proposal,
            list_proposals,
            format_proposals_telegram,
            evaluate_proposal,
            promote_to_approval,
            approve_proposal,
            reject_proposal,
        )
        assert callable(add_observation)
        assert callable(run_research_cycle)

    def test_proposal_status_lifecycle(self):
        """Proposals follow DRAFT -> SANDBOX_PENDING -> APPROVED -> ACTIVE."""
        from llm.strategy_discovery.proposals import ProposalStatus
        assert hasattr(ProposalStatus, "DRAFT")
        assert hasattr(ProposalStatus, "SANDBOX_PENDING")
        assert hasattr(ProposalStatus, "SANDBOX_PASSED")
        assert hasattr(ProposalStatus, "APPROVED")
        assert hasattr(ProposalStatus, "ACTIVE")
        assert ProposalStatus.DRAFT.value == "draft"

    def test_corpus_add_and_load(self):
        """add_observation writes, load_observations reads back."""
        from llm.strategy_discovery.corpus import add_observation, load_observations
        with tempfile.TemporaryDirectory() as tmpdir:
            obs_file = os.path.join(tmpdir, "observations.jsonl")
            with patch("llm.strategy_discovery.corpus._OBSERVATIONS_FILE", obs_file), \
                 patch("llm.strategy_discovery.corpus._CORPUS_DIR", tmpdir):
                add_observation(
                    category="trade_outcome",
                    symbol="BTC",
                    regime="trending_up",
                    observation="BTC breakout win: pnl=$50",
                )
                obs = load_observations()
                assert len(obs) >= 1
                assert obs[-1]["symbol"] == "BTC"
                assert obs[-1]["category"] == "trade_outcome"

    def test_corpus_summary_returns_dict(self):
        from llm.strategy_discovery.corpus import get_corpus_summary
        with tempfile.TemporaryDirectory() as tmpdir:
            obs_file = os.path.join(tmpdir, "observations.jsonl")
            with patch("llm.strategy_discovery.corpus._OBSERVATIONS_FILE", obs_file), \
                 patch("llm.strategy_discovery.corpus._CORPUS_DIR", tmpdir):
                summary = get_corpus_summary()
                assert isinstance(summary, dict)

    def test_build_research_prompt_returns_string(self):
        from llm.strategy_discovery.research_agent import build_research_prompt
        prompt = build_research_prompt(corpus_summary={"total_observations": 0, "categories": {}})
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ── Wiring Integration (multi_strategy_main.py imports) ────

class TestWiringImports:
    """Verify that multi_strategy_main.py can import all Wave 3 features."""

    def test_survival_pressure_available(self):
        try:
            from llm.survival_pressure import (
                record_trade_outcome,
                get_survival_context_for_llm,
                get_survival_report,
            )
            available = True
        except ImportError:
            available = False
        assert available

    def test_learning_mode_available(self):
        try:
            from llm.learning_mode import (
                is_learning_mode_active,
                get_current_phase,
                record_signal_observed,
                record_trade_observed,
                record_counterfactual,
                apply_learning_constraints,
                get_learning_report,
                LearningPhase,
            )
            available = True
        except ImportError:
            available = False
        assert available

    def test_progression_available(self):
        try:
            from llm.progression import evaluate_progression, format_progression_status
            available = True
        except ImportError:
            available = False
        assert available

    def test_uplift_available(self):
        try:
            from llm.uplift_analytics import compute_uplift, format_uplift_report
            available = True
        except ImportError:
            available = False
        assert available

    def test_adaptive_risk_available(self):
        try:
            from execution.adaptive_risk import get_adaptive_risk
            available = True
        except ImportError:
            available = False
        assert available

    def test_strategy_pruning_available(self):
        try:
            from execution.strategy_pruning import evaluate_and_adjust, get_strategy_weight
            available = True
        except ImportError:
            available = False
        assert available

    def test_copy_classifier_available(self):
        try:
            from classification.human_copy_classifier import classify_human_copy_tradable, CopyTradeResult
            available = True
        except ImportError:
            available = False
        assert available

    def test_self_performance_available(self):
        try:
            from llm.self_performance import get_compact_stats
            available = True
        except ImportError:
            available = False
        assert available

    def test_http_client_available(self):
        try:
            from http_client import get_http_client
            available = True
        except ImportError:
            available = False
        assert available

    def test_strategy_discovery_available(self):
        try:
            from llm.strategy_discovery import (
                StrategyProposal,
                ProposalStatus,
                add_observation,
                run_research_cycle,
                evaluate_proposal,
            )
            available = True
        except ImportError:
            available = False
        assert available
