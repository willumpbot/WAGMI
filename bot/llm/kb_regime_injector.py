"""
KB Regime Injector - Inject regime-specific KB parameters.

Adjusts KB parameters based on current market regime to reflect empirically
different agent performance in trending vs consolidating vs panic markets.
"""

import json
from typing import Dict, Any, Optional


class KBRegimeInjector:
    """Inject regime-specific KB parameters based on market conditions."""

    # Empirically optimized parameters per regime
    REGIME_OVERRIDES = {
        "trend": {
            "trend_long": {
                "confidence_threshold": 40,  # Lower threshold, trending is easy to spot
                "expected_go_wr": 0.58,  # Higher WR in obvious trends
                "expected_skip_wr": 0.18,
                "leverage_multiplier": 1.2,
            },
            "trend_short": {
                "confidence_threshold": 40,
                "expected_go_wr": 0.55,
                "expected_skip_wr": 0.20,
                "leverage_multiplier": 1.2,
            }
        },
        "consolidation": {
            "consolidation_range": {
                "confidence_threshold": 55,  # Higher threshold, ranges are choppy
                "expected_go_wr": 0.35,  # Lower WR, more noise
                "expected_skip_wr": 0.28,
                "leverage_multiplier": 0.7,
            }
        },
        "volatility": {
            "high_volatility": {
                "confidence_threshold": 50,
                "expected_go_wr": 0.42,
                "expected_skip_wr": 0.25,
                "leverage_multiplier": 0.6,  # Reduce size in volatility
            },
            "panic": {
                "confidence_threshold": 60,  # Much higher threshold
                "expected_go_wr": 0.30,  # Panic is unpredictable
                "expected_skip_wr": 0.20,
                "leverage_multiplier": 0.4,  # Minimal positions
            }
        },
        "mean_reversion": {
            "mean_reversion": {
                "confidence_threshold": 45,
                "expected_go_wr": 0.52,
                "expected_skip_wr": 0.23,
                "leverage_multiplier": 1.0,
            }
        }
    }

    @classmethod
    def get_regime_params(cls, regime: str, directional_bias: Optional[str] = None) -> Dict[str, Any]:
        """
        Get KB parameters for a specific regime.

        Args:
            regime: Market regime (trend, consolidation, volatility, mean_reversion, etc.)
            directional_bias: For trend regimes, either "long" or "short"

        Returns:
            Dict of regime-specific parameters
        """
        # Normalize regime name
        regime_lower = regime.lower() if regime else "unknown"

        # Check if regime has specific overrides
        for regime_family, subregimes in cls.REGIME_OVERRIDES.items():
            if regime_lower.startswith(regime_family):
                # Try to find specific subregime
                for subregime_name, params in subregimes.items():
                    if regime_lower in subregime_name or subregime_name in regime_lower:
                        return params.copy()

                # Return first available subregime for this family
                return list(subregimes.values())[0].copy()

        # Default parameters for unknown regimes
        return {
            "confidence_threshold": 45,
            "expected_go_wr": 0.50,
            "expected_skip_wr": 0.221,
            "leverage_multiplier": 1.0,
        }

    @classmethod
    def inject_regime_params(cls, snap_data: Dict[str, Any], kb_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inject regime-specific KB parameters into snapshot context.

        Args:
            snap_data: Snapshot data including regime information
            kb_context: Base KB context to extend

        Returns:
            Enhanced KB context with regime-specific parameters
        """
        regime = snap_data.get("regime", "unknown")
        directional_bias = snap_data.get("directional_bias")

        regime_params = cls.get_regime_params(regime, directional_bias)

        # Merge regime params into KB context
        kb_context.update(regime_params)
        kb_context["regime"] = regime
        kb_context["regime_specific"] = True
        kb_context["regime_params"] = regime_params

        return kb_context

    @classmethod
    def adjust_agent_params(cls, agent_name: str, agent_context: Dict[str, Any], regime: str) -> Dict[str, Any]:
        """
        Adjust agent-specific parameters based on regime.

        Args:
            agent_name: Name of the agent
            agent_context: Agent context to modify
            regime: Current market regime

        Returns:
            Modified agent context with regime adjustments
        """
        regime_params = cls.get_regime_params(regime)

        if agent_name.lower() == "trade_agent":
            agent_context["confidence_threshold"] = regime_params["confidence_threshold"]
            agent_context["expected_go_wr"] = regime_params["expected_go_wr"]
            agent_context["expected_skip_wr"] = regime_params["expected_skip_wr"]
            agent_context["regime_adjusted"] = True

        elif agent_name.lower() == "risk_agent":
            leverage_mult = regime_params.get("leverage_multiplier", 1.0)
            base_leverage = agent_context.get("base_leverage", 1.0)
            agent_context["regime_adjusted_leverage"] = base_leverage * leverage_mult

        elif agent_name.lower() == "critic_agent":
            # In volatile/panic regimes, be more critical
            if regime in ["high_volatility", "panic"]:
                agent_context["veto_threshold_wr_drift"] = (
                    agent_context.get("veto_threshold_wr_drift", 5) * 0.7  # Lower threshold
                )

        return agent_context


def inject_regime_kb(snap_data: Dict[str, Any], kb_context: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to inject regime-specific KB parameters."""
    return KBRegimeInjector.inject_regime_params(snap_data, kb_context)


if __name__ == "__main__":
    # Test regime parameter extraction
    test_regimes = [
        "trend_long",
        "trend_short",
        "consolidation_range",
        "high_volatility",
        "panic",
        "mean_reversion",
        "unknown"
    ]

    print("=" * 100)
    print("REGIME-SPECIFIC KB PARAMETERS")
    print("=" * 100)

    for regime in test_regimes:
        params = KBRegimeInjector.get_regime_params(regime)
        print(f"\n{regime}:")
        for key, value in params.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}" if key.endswith("_wr") else f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")

    print("\n" + "=" * 100)
