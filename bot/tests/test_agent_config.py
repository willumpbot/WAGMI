"""Tests for Agent Configuration (W4-E)."""

import pytest
from trading_config import TradingConfig


class TestAgentConfiguration:
    """Test agent enable/disable and config flags."""

    def test_default_agent_configuration(self):
        """Should load default agent configuration."""
        config = TradingConfig()
        
        # Core agents enabled by default
        assert config.agent_regime_enabled is True
        assert config.agent_trade_enabled is True
        assert config.agent_risk_enabled is True
        assert config.agent_critic_enabled is True
        assert config.agent_learning_enabled is True
        assert config.agent_exit_enabled is True
        
        # Optional agents disabled by default
        assert config.agent_scout_enabled is False
        assert config.agent_overseer_enabled is False
        assert config.agent_quant_enabled is False
        assert config.agent_opportunist_enabled is False
        assert config.agent_adversary_enabled is False
        assert config.agent_swarm_enabled is False

    def test_agent_min_confidence_thresholds(self):
        """Should have appropriate min confidence thresholds."""
        config = TradingConfig()
        
        # Regime, Trade, Risk: always run (0.0 threshold)
        assert config.agent_regime_min_confidence == 0.0
        assert config.agent_trade_min_confidence == 0.0
        assert config.agent_risk_min_confidence == 0.0
        
        # Critic: only high-confidence trades (50% threshold)
        assert config.agent_critic_min_confidence == 50.0
        
        # Exit: always run on open positions
        assert config.agent_exit_min_confidence == 0.0

    def test_agent_model_overrides(self):
        """Should support per-agent model overrides."""
        config = TradingConfig()
        
        # Default: no overrides (empty strings)
        assert config.agent_regime_model == ""
        assert config.agent_trade_model == ""
        assert config.agent_risk_model == ""
        assert config.agent_critic_model == ""
        assert config.agent_exit_model == ""

    def test_agent_config_from_env(self, monkeypatch):
        """Should load agent config from environment variables."""
        # Set environment variables
        monkeypatch.setenv("AGENT_REGIME_ENABLED", "false")
        monkeypatch.setenv("AGENT_CRITIC_ENABLED", "true")
        monkeypatch.setenv("AGENT_OPPORTUNIST_ENABLED", "true")
        monkeypatch.setenv("AGENT_CRITIC_MIN_CONFIDENCE", "75.0")
        monkeypatch.setenv("AGENT_TRADE_MODEL", "opus")
        
        config = TradingConfig()
        
        assert config.agent_regime_enabled is False
        assert config.agent_critic_enabled is True
        assert config.agent_opportunist_enabled is True
        assert config.agent_critic_min_confidence == 75.0
        assert config.agent_trade_model == "opus"

    def test_learning_loop_agents(self):
        """Should enable learning loop agents (Opportunist, Adversary, Swarm)."""
        config = TradingConfig()
        
        # All learning loop agents disabled by default
        assert config.agent_opportunist_enabled is False
        assert config.agent_adversary_enabled is False
        assert config.agent_swarm_enabled is False

    def test_specialist_agents(self):
        """Should support optional specialist agents (Scout, Overseer, Quant)."""
        config = TradingConfig()
        
        # All specialist agents disabled by default
        assert config.agent_scout_enabled is False
        assert config.agent_overseer_enabled is False
        assert config.agent_quant_enabled is False

    def test_agent_cost_aware_tuning(self, monkeypatch):
        """Should support cost-aware agent tuning."""
        # Expensive critic disabled for low-confidence trades
        monkeypatch.setenv("AGENT_CRITIC_MIN_CONFIDENCE", "85.0")
        config = TradingConfig()
        
        assert config.agent_critic_min_confidence == 85.0
        # High-confidence trades get critic scrutiny; low-confidence skip it

    def test_agent_boolean_parsing(self, monkeypatch):
        """Should correctly parse boolean environment variables."""
        test_cases = [
            ("true", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
        ]
        
        for env_value, expected in test_cases:
            monkeypatch.setenv("AGENT_REGIME_ENABLED", env_value)
            config = TradingConfig()
            assert config.agent_regime_enabled is expected

    def test_all_agent_flags_present(self):
        """Should have all expected agent configuration flags."""
        config = TradingConfig()
        
        # Core 9 agents
        assert hasattr(config, "agent_regime_enabled")
        assert hasattr(config, "agent_trade_enabled")
        assert hasattr(config, "agent_risk_enabled")
        assert hasattr(config, "agent_critic_enabled")
        assert hasattr(config, "agent_learning_enabled")
        assert hasattr(config, "agent_exit_enabled")
        assert hasattr(config, "agent_scout_enabled")
        assert hasattr(config, "agent_overseer_enabled")
        assert hasattr(config, "agent_quant_enabled")
        
        # Learning loop agents (W4-ABC)
        assert hasattr(config, "agent_opportunist_enabled")
        assert hasattr(config, "agent_adversary_enabled")
        assert hasattr(config, "agent_swarm_enabled")
        
        # Model overrides
        assert hasattr(config, "agent_regime_model")
        assert hasattr(config, "agent_trade_model")
        assert hasattr(config, "agent_risk_model")
        assert hasattr(config, "agent_critic_model")
        assert hasattr(config, "agent_exit_model")
        
        # Min confidence thresholds
        assert hasattr(config, "agent_regime_min_confidence")
        assert hasattr(config, "agent_trade_min_confidence")
        assert hasattr(config, "agent_risk_min_confidence")
        assert hasattr(config, "agent_critic_min_confidence")
        assert hasattr(config, "agent_exit_min_confidence")