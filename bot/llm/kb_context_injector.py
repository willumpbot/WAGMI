"""
KB Context Injector - Wires empirical KB parameters into agent pipeline.
Automatically injects current KB configuration into agent enriched context.
"""

import json
from pathlib import Path
from datetime import datetime


class KBContextInjector:
    """Inject KB parameters into agent pipeline context"""

    def __init__(self, data_dir="."):
        self.data_dir = Path(data_dir)
        self.kb_config = None
        self.load_latest_kb_config()

    def load_latest_kb_config(self):
        """Load the latest KB configuration"""
        # Try kb_v*.json files first (from autonomous loops)
        kb_files = list(self.data_dir.glob("kb_v*.json"))
        if kb_files:
            latest = sorted(kb_files, key=lambda p: p.stat().st_mtime)[-1]
            with open(latest) as f:
                data = json.load(f)

            # Convert to expected format if needed
            if "optimal_config" in data and "optimal_parameters" not in data:
                data["optimal_parameters"] = {
                    "confidence_threshold": data["optimal_config"].get("conf_threshold", 45),
                    "expected_go_wr": 0.50,  # Default expectations
                    "expected_skip_wr": 0.221
                }

            self.kb_config = data
            return

        # Fallback: try kb_config_v*.json files
        config_files = list(self.data_dir.glob("kb_config_v*.json"))
        if config_files:
            latest = sorted(config_files, key=lambda p: p.stat().st_mtime)[-1]
            with open(latest) as f:
                self.kb_config = json.load(f)

    def inject_into_agent_context(self, agent_name, agent_context, symbol=None):
        """
        Inject KB parameters into agent context before execution.
        agent_context is the input dict to the agent.
        symbol: optional symbol for symbol-specific parameter injection
        """
        if not self.kb_config:
            return agent_context

        # Add KB version to all agents
        agent_context["kb_version"] = self.kb_config.get("kb_version") or self.kb_config.get("version")
        agent_context["kb_cycle"] = self.kb_config.get("cycle")

        # Extract symbol-specific parameters if symbol provided
        symbol_params = {}
        if symbol:
            symbol_params = self.get_symbol_specific_params(symbol) or {}

        if agent_name.lower() == "regime_agent":
            agent_context["current_edges"] = self.kb_config.get("market_profitability_surface")
            agent_context["regime_performance"] = self.kb_config.get("market_profitability_surface")
            if symbol_params:
                agent_context["symbol"] = symbol
                agent_context["symbol_volatility_profile"] = symbol_params.get("volatility_profile")
                agent_context["symbol_regime_bias"] = symbol_params.get("regime_bias")

        elif agent_name.lower() == "trade_agent":
            params = self.kb_config.get("optimal_parameters", {})
            agent_context["confidence_threshold"] = symbol_params.get("confidence_threshold") or params.get("confidence_threshold", 45)
            agent_context["setup_score_floor"] = agent_context["confidence_threshold"]
            agent_context["expected_go_wr"] = symbol_params.get("expected_go_wr") or params.get("expected_go_wr", 0.50)
            agent_context["expected_skip_wr"] = symbol_params.get("expected_skip_wr") or params.get("expected_skip_wr", 0.221)
            if symbol:
                agent_context["symbol"] = symbol
                agent_context["symbol_specific_params"] = bool(symbol_params)

        elif agent_name.lower() == "risk_agent":
            if self.kb_config.get("agent_configuration", {}).get("risk_agent"):
                agent_context["base_leverage"] = self.kb_config["agent_configuration"]["risk_agent"]["base_leverage"]
                agent_context["confidence_multiplier"] = self.kb_config["agent_configuration"]["risk_agent"]["confidence_multiplier"]
                agent_context["regime_multiplier"] = self.kb_config["agent_configuration"]["risk_agent"]["regime_multiplier"]
            if symbol_params and symbol_params.get("volatility_profile") == "high":
                agent_context["base_leverage"] = agent_context.get("base_leverage", 1.0) * 0.8

        elif agent_name.lower() == "critic_agent":
            if self.kb_config.get("agent_configuration", {}).get("critic_agent"):
                agent_context["veto_threshold_wr_drift"] = self.kb_config["agent_configuration"]["critic_agent"]["veto_threshold_wr_drift"]
                agent_context["alert_bounds"] = {
                    "go_wr": self.kb_config["agent_configuration"]["critic_agent"]["alert_on_go_wr_outside"],
                    "skip_wr": self.kb_config["agent_configuration"]["critic_agent"]["alert_on_skip_wr_outside"]
                }

        elif agent_name.lower() == "learning_agent":
            if self.kb_config.get("agent_configuration", {}).get("learning_agent"):
                agent_context["target_go_wr"] = self.kb_config["agent_configuration"]["learning_agent"]["target_go_wr"]
                agent_context["target_skip_wr"] = self.kb_config["agent_configuration"]["learning_agent"]["target_skip_wr"]
            agent_context["kb_reference"] = self.kb_config.get("kb_version") or self.kb_config.get("version")
            if symbol:
                agent_context["symbol"] = symbol
                agent_context["symbol_go_wr"] = symbol_params.get("expected_go_wr")
                agent_context["symbol_skip_wr"] = symbol_params.get("expected_skip_wr")

        elif agent_name.lower() == "exit_agent":
            agent_context["monitor_kb_divergence"] = True
            params = self.kb_config.get("optimal_parameters", {})
            agent_context["kb_expected_go_wr"] = symbol_params.get("expected_go_wr") or params.get("expected_go_wr", 0.50)
            agent_context["kb_expected_skip_wr"] = symbol_params.get("expected_skip_wr") or params.get("expected_skip_wr", 0.221)
            if symbol:
                agent_context["symbol"] = symbol
                agent_context["symbol_specific_thresholds"] = bool(symbol_params)

        return agent_context

    def get_kb_summary(self):
        """Return KB summary for logging/monitoring"""
        if not self.kb_config:
            return None

        params = self.kb_config.get("optimal_parameters", {})
        return {
            "kb_version": self.kb_config.get("version") or self.kb_config.get("kb_version"),
            "cycle": self.kb_config.get("cycle"),
            "convergence": self.kb_config.get("empirical_validation", {}).get("convergence"),
            "confidence_threshold": params.get("confidence_threshold", 45),
            "expected_go_wr": params.get("expected_go_wr", 0.50),
            "expected_skip_wr": params.get("expected_skip_wr", 0.221)
        }

    def get_symbol_specific_params(self, symbol):
        """Extract symbol-specific KB parameters if available."""
        if not self.kb_config:
            return None

        # Check if KB has symbol-specific performance data
        symbol_stats = self.kb_config.get("symbol_statistics", {})
        if symbol not in symbol_stats:
            return None

        sym_data = symbol_stats[symbol]
        return {
            "confidence_threshold": sym_data.get("optimal_threshold", 45),
            "expected_go_wr": sym_data.get("go_win_rate", 0.50),
            "expected_skip_wr": sym_data.get("skip_win_rate", 0.221),
            "volatility_profile": sym_data.get("volatility_profile", "normal"),
            "regime_bias": sym_data.get("regime_bias", {}),
        }

    def inject_into_context(self, snap_data, symbol=None):
        """Inject KB parameters into snapshot context for agents."""
        if not self.kb_config:
            return snap_data

        params = self.kb_config.get("optimal_parameters", {})

        # Start with global parameters
        kb_context = {
            "version": self.kb_config.get("version") or self.kb_config.get("kb_version"),
            "confidence_threshold": params.get("confidence_threshold", 45),
            "expected_go_wr": params.get("expected_go_wr", 0.50),
            "expected_skip_wr": params.get("expected_skip_wr", 0.221),
        }

        # Override with symbol-specific parameters if available
        if symbol:
            symbol_params = self.get_symbol_specific_params(symbol)
            if symbol_params:
                kb_context["symbol_specific"] = True
                kb_context.update(symbol_params)

        snap_data["knowledge_base"] = kb_context
        return snap_data


# Global singleton
_injector = None


def get_kb_injector():
    """Get or create KB injector singleton."""
    global _injector
    if _injector is None:
        _injector = KBContextInjector(data_dir="data")
    return _injector


def inject_kb_context(snap_data):
    """Convenience function to inject KB context."""
    injector = get_kb_injector()
    return injector.inject_into_context(snap_data)


if __name__ == "__main__":
    # Test injection
    injector = KBContextInjector(data_dir="data")
    summary = injector.get_kb_summary()
    print(f"KB Summary: {summary}")
