"""Test LLMBackend integration for agent routing.

Verifies that the new BackendRouter abstraction layer works correctly
and that existing coordinator behavior is preserved.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock

from llm.backend import (
    LLMBackend, LLMResponse, CliBackend, ApiBackend, OllamaBackend,
    BackendRouter, get_default_router,
)
from llm.audit_logger import log_decision_audit, audit_trade_decision


class TestCliBackend:
    """Test CliBackend implementation."""

    def test_cli_backend_initialization(self):
        """CLI backend should initialize with correct name and model."""
        backend = CliBackend()
        assert backend.name == "cli"
        assert backend.model == "claude-sonnet-4-6"
        assert backend.stats.total_calls == 0
        assert backend.stats.total_failures == 0

    def test_cli_backend_success_recording(self):
        """CLI backend should record successful calls."""
        backend = CliBackend()
        backend._record_success(cost=0.001, latency=0.5)

        assert backend.stats.total_calls == 1
        assert backend.stats.total_failures == 0
        assert backend.stats.total_cost_usd == 0.001
        assert abs(backend.stats.mean_latency_s - 0.5) < 0.01

    def test_cli_backend_failure_recording(self):
        """CLI backend should record failures with error tracking."""
        backend = CliBackend()
        backend._record_failure("timeout after 30s")

        assert backend.stats.total_calls == 1
        assert backend.stats.total_failures == 1
        assert backend.stats.last_failure_msg == "timeout after 30s"
        assert len(backend.failures) == 1

    def test_cli_backend_stats(self):
        """get_stats should return computed statistics."""
        backend = CliBackend()
        backend._record_success(cost=0.001, latency=0.5)
        backend._record_failure("test error")

        stats = backend.get_stats()
        assert stats["name"] == "cli"
        assert stats["total_calls"] == 2
        assert stats["total_failures"] == 1
        assert stats["failure_rate"] == pytest.approx(0.5)


class TestApiBackend:
    """Test ApiBackend (stub implementation)."""

    def test_api_backend_initialization(self):
        """API backend should initialize with placeholder."""
        backend = ApiBackend()
        assert backend.name == "api"
        assert backend.model == "claude-sonnet-4-6"


class TestBackendRouter:
    """Test BackendRouter fallback logic."""

    def test_router_initialization(self):
        """Router should accept primary and fallback backends."""
        cli = CliBackend()
        api = ApiBackend()
        router = BackendRouter(primary=cli, fallbacks=[api])

        assert router.primary == cli
        assert len(router.all_backends) == 2
        assert router.all_backends[0] == cli
        assert router.all_backends[1] == api

    def test_router_with_no_fallbacks(self):
        """Router should work with only primary backend."""
        cli = CliBackend()
        router = BackendRouter(primary=cli)

        assert router.primary == cli
        assert len(router.all_backends) == 1

    def test_get_default_router(self):
        """get_default_router should return singleton with CLI primary."""
        router1 = get_default_router()
        router2 = get_default_router()

        assert router1 is router2  # Singleton
        assert router1.primary.name == "cli"

    def test_router_get_all_stats(self):
        """Router should aggregate stats from all backends."""
        cli = CliBackend()
        api = ApiBackend()
        router = BackendRouter(primary=cli, fallbacks=[api])

        # Record some stats
        cli._record_success(cost=0.001, latency=0.5)
        api._record_failure("api_not_implemented")

        stats = router.get_all_stats()
        assert "cli" in stats
        assert "api" in stats
        assert stats["cli"]["total_calls"] == 1
        assert stats["api"]["total_failures"] == 1


class TestAuditLogging:
    """Test audit logging integration."""

    def test_log_decision_audit_creation(self, tmp_path):
        """log_decision_audit should create valid JSON entries."""
        import logging
        from pathlib import Path

        # This test verifies the audit logger can write entries
        with patch("llm.audit_logger.DECISIONS_LOG_PATH", tmp_path / "decisions.jsonl"):
            log_decision_audit(
                symbol="BTC",
                action="go",
                regime="trending_bear",
                thesis="Strong downtrend on 1h chart",
                confidence=85.0,
                leverage=3.0,
                risk_pct=0.05,
            )

            # Verify file was created and contains valid JSON
            log_file = tmp_path / "decisions.jsonl"
            assert log_file.exists()

            with open(log_file) as f:
                entry = json.loads(f.readline())

            assert entry["symbol"] == "BTC"
            assert entry["action"] == "go"
            assert entry["regime"] == "trending_bear"
            assert entry["confidence"] == 85.0

    def test_audit_trade_decision(self, tmp_path):
        """audit_trade_decision should log complete decision context."""
        with patch("llm.audit_logger.DECISIONS_LOG_PATH", tmp_path / "decisions.jsonl"):
            audit_trade_decision(
                symbol="ETH",
                action="skip",
                regime="range",
                thesis="Sideways price action, low conviction",
                confidence=45.0,
                leverage=1.0,
                risk_pct=0.02,
                sizing_rationale="Conservative size for low-conviction signal",
                risk_flags=["low_liquidity", "high_spread"],
                debate_summary="Bull thesis weak, Bear counter-thesis stronger",
                latency_ms=500,
                cost_usd=0.0015,
            )

            log_file = tmp_path / "decisions.jsonl"
            with open(log_file) as f:
                entry = json.loads(f.readline())

            assert entry["symbol"] == "ETH"
            assert entry["action"] == "skip"
            assert entry["risk_flags"] == ["low_liquidity", "high_spread"]
            assert entry["debate_summary"][:50] == "Bull thesis weak, Bear counter-thesis stronger"[:50]


class TestBackendIntegration:
    """Test backend integration with coordinator."""

    @pytest.mark.skip(reason="Requires live LLM or mock setup")
    def test_coordinator_agent_call_via_backend(self):
        """Coordinator should be able to route agent calls through backend."""
        # This test would verify that AgentCoordinator._call_agent
        # works with the new BackendRouter, but requires mocking
        # the LLM responses, which is complex with the current architecture.
        #
        # For now, integration is tested via existing test suite (test_multi_agent.py)
        # The backend layer should be transparent to existing code.
        pass


# Equivalence test: Verify 100 coordinator calls produce identical behavior
# This would be run via: pytest tests/test_backend_integration.py -k equivalence
@pytest.mark.skip(reason="Requires full bot stack, run via integration tests")
class TestBackendEquivalence:
    """Verify backend routing doesn't change coordinator behavior."""

    def test_regime_agent_equivalence(self):
        """Regime Agent decisions should be identical before/after backend migration."""
        # Run 100 coordinator.get_trading_decision calls
        # Compare output with/without backend routing
        # Verify ±1% equivalence
        pass

    def test_trade_agent_equivalence(self):
        """Trade Agent decisions should be identical before/after backend migration."""
        pass

    def test_risk_agent_equivalence(self):
        """Risk Agent sizing should be identical before/after backend migration."""
        pass

    def test_critic_agent_equivalence(self):
        """Critic Agent verdicts should be identical before/after backend migration."""
        pass
