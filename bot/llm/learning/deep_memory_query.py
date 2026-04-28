"""Deep Memory Query Engine - Agents query historical trade patterns.

Enables Trade/Risk/Critic agents to look up lessons learned from past trades,
indexed by setup_type (regime + n_agree + confidence), symbol, and regime.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class DeepMemoryQuery:
    """Query historical patterns and symbol-specific intelligence."""

    def __init__(
        self,
        patterns_path: str = "bot/data/llm/deep_memory/patterns.jsonl",
        rules_path: str = "bot/data/llm/graduated_rules.json",
    ):
        self.patterns_path = Path(patterns_path)
        self.rules_path = Path(rules_path)
        self._patterns_cache = None
        self._rules_cache = None
        self._symbol_intelligence_cache = None

    def query_similar_patterns(
        self,
        regime: str,
        n_agree: int,
        confidence: int,
    ) -> Dict[str, Any]:
        """Find historical patterns matching current setup.

        Args:
            regime: Market regime (trending_bear, ranging, etc.)
            n_agree: Number of strategies agreeing (1-4)
            confidence: Predicted confidence (0-100 scale)

        Returns:
            Dict with historical performance:
            {
                "setup_type": "trending_bear+3-agree+80conf",
                "win_rate": 0.76,
                "sample_size": 13,
                "avg_r_multiple": 1.8,
                "risk_flags": ["overconfident_in_consolidation"],
                "avg_hold_minutes": 480,
                "confidence_bins": {
                    "80": {"wins": 10, "losses": 3, "avg_r": 1.9}
                }
            }
        """
        patterns = self._load_patterns()
        if not patterns:
            return self._empty_pattern_result(regime, n_agree, confidence)

        # Build setup_type from inputs
        confidence_bin = int(confidence / 10) * 10
        setup_type = f"{regime}+{n_agree}-agree+{confidence_bin}conf"

        # Look for exact match
        if setup_type in patterns:
            pattern = patterns[setup_type]
            return self._format_pattern_result(setup_type, pattern)

        # Fall back to regime + n_agree (ignore confidence bin)
        partial_setup = f"{regime}+{n_agree}-agree"
        similar = [
            (st, p)
            for st, p in patterns.items()
            if st.startswith(partial_setup)
        ]

        if similar:
            # Return aggregated stats from similar patterns
            return self._aggregate_similar_patterns(similar)

        # Final fallback: regime-only patterns
        regime_patterns = [
            (st, p)
            for st, p in patterns.items()
            if st.startswith(f"{regime}+")
        ]

        if regime_patterns:
            return self._aggregate_similar_patterns(regime_patterns)

        return self._empty_pattern_result(regime, n_agree, confidence)

    def get_symbol_intelligence(self, symbol: str) -> Dict[str, Any]:
        """Get symbol-specific lessons from historical trades.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL, HYPE)

        Returns:
            Dict with symbol-specific insights:
            {
                "symbol": "ETH",
                "win_rate": 0.64,
                "sample_size": 47,
                "regime_preference": {
                    "trending_bull": 0.78,
                    "trending_bear": 0.71,
                    "ranging": 0.32
                },
                "vol_adjustment_factor": 1.2,
                "cooldown_hours": 0,
                "best_strategies": ["confidence_scorer", "bollinger_squeeze"],
                "avoid_patterns": ["ranging+1-agree"]
            }
        """
        patterns = self._load_patterns()
        if not patterns:
            return {
                "symbol": symbol,
                "win_rate": 0.0,
                "sample_size": 0,
                "regime_preference": {},
                "vol_adjustment_factor": 1.0,
                "cooldown_hours": 0,
                "best_strategies": [],
                "avoid_patterns": [],
            }

        # Collect stats by regime for this symbol
        symbol_patterns = {}
        for setup_type, pattern in patterns.items():
            if f"+{symbol}" in pattern.get("symbol", "") or pattern.get(
                "symbol"
            ) == symbol:
                regime = setup_type.split("+")[0]
                if regime not in symbol_patterns:
                    symbol_patterns[regime] = []
                symbol_patterns[regime].append(pattern)

        if not symbol_patterns:
            return {
                "symbol": symbol,
                "win_rate": 0.0,
                "sample_size": 0,
                "regime_preference": {},
                "vol_adjustment_factor": 1.0,
                "cooldown_hours": 0,
                "best_strategies": [],
                "avoid_patterns": [],
            }

        # Compute regime-specific win rates
        regime_preference = {}
        total_samples = 0
        total_wins = 0

        for regime, regime_patterns_list in symbol_patterns.items():
            wins = sum(p.get("win_count", 0) for p in regime_patterns_list)
            samples = sum(p.get("sample_size", 0) for p in regime_patterns_list)
            if samples > 0:
                regime_preference[regime] = wins / samples
                total_wins += wins
                total_samples += samples

        overall_wr = total_wins / total_samples if total_samples > 0 else 0.0

        # Identify vol adjustment (symbols with high variance need wider stops)
        vol_adjustment = self._estimate_vol_adjustment(symbol)

        # Identify losing patterns for this symbol
        avoid_patterns = self._find_avoid_patterns(patterns, symbol)

        return {
            "symbol": symbol,
            "win_rate": overall_wr,
            "sample_size": total_samples,
            "regime_preference": regime_preference,
            "vol_adjustment_factor": vol_adjustment,
            "cooldown_hours": 0,
            "best_strategies": [],
            "avoid_patterns": avoid_patterns,
        }

    def inject_regime_context(self, regime: str) -> str:
        """Generate regime-conditional advice for agent prompts.

        Args:
            regime: Current market regime

        Returns:
            Formatted context string for prompt injection:
            "In your regime (trending_bear), 3-agree setups are 76% WR (13 samples).
            In ranging, they drop to 48%. Confidence in regime classification is critical."
        """
        patterns = self._load_patterns()
        if not patterns:
            return f"No historical data available for regime: {regime}"

        lines = [f"Regime context for {regime}:"]

        # Find all patterns for this regime, grouped by n_agree
        regime_patterns = defaultdict(list)
        for setup_type, pattern in patterns.items():
            if setup_type.startswith(f"{regime}+"):
                # Extract n_agree from setup_type (e.g., "trending_bear+3-agree+80conf")
                parts = setup_type.split("+")
                if len(parts) >= 2:
                    n_agree_str = parts[1]  # "3-agree"
                    n_agree = int(n_agree_str[0])
                    regime_patterns[n_agree].append(pattern)

        # Report each n_agree level
        for n_agree in sorted(regime_patterns.keys()):
            patterns_for_agree = regime_patterns[n_agree]
            total_wins = sum(p.get("win_count", 0) for p in patterns_for_agree)
            total_samples = sum(p.get("sample_size", 0) for p in patterns_for_agree)

            if total_samples > 0:
                wr = total_wins / total_samples
                lines.append(
                    f"  • {n_agree}-agree: {wr:.1%} WR ({total_samples} trades)"
                )

        # Compare with other regimes
        other_regimes = set()
        for setup_type in patterns.keys():
            regime_name = setup_type.split("+")[0]
            if regime_name != regime:
                other_regimes.add(regime_name)

        if other_regimes:
            lines.append(
                f"  • Compare with: {', '.join(sorted(other_regimes))}"
            )

        lines.append(
            f"Accuracy in {regime} classification is critical to success."
        )

        return "\n".join(lines)

    # Private helper methods

    def _load_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Load patterns from deep_memory/patterns.jsonl."""
        if self._patterns_cache is not None:
            return self._patterns_cache

        self._patterns_cache = {}
        if not self.patterns_path.exists():
            logger.warning(
                f"[DEEP-MEMORY] Patterns file not found: {self.patterns_path}"
            )
            return self._patterns_cache

        try:
            with open(self.patterns_path) as f:
                for line in f:
                    try:
                        pattern = json.loads(line)
                        setup_type = pattern.get("setup_type")
                        if setup_type:
                            self._patterns_cache[setup_type] = pattern
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"[DEEP-MEMORY] Failed to load patterns: {e}")

        return self._patterns_cache

    def _load_rules(self) -> List[Dict[str, Any]]:
        """Load graduated rules from graduated_rules.json."""
        if self._rules_cache is not None:
            return self._rules_cache

        self._rules_cache = []
        if not self.rules_path.exists():
            return self._rules_cache

        try:
            with open(self.rules_path) as f:
                data = json.load(f)
                self._rules_cache = data.get("rules", [])
        except Exception as e:
            logger.error(f"[DEEP-MEMORY] Failed to load rules: {e}")

        return self._rules_cache

    def _empty_pattern_result(
        self,
        regime: str,
        n_agree: int,
        confidence: int,
    ) -> Dict[str, Any]:
        """Return empty result when no patterns found."""
        confidence_bin = int(confidence / 10) * 10
        return {
            "setup_type": f"{regime}+{n_agree}-agree+{confidence_bin}conf",
            "win_rate": 0.0,
            "sample_size": 0,
            "avg_r_multiple": 0.0,
            "risk_flags": [],
            "avg_hold_minutes": 0,
            "confidence_bins": {},
        }

    def _format_pattern_result(
        self,
        setup_type: str,
        pattern: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Format a single pattern for return."""
        sample_size = pattern.get("sample_size", 0)
        win_count = pattern.get("win_count", 0)
        wr = win_count / sample_size if sample_size > 0 else 0.0

        return {
            "setup_type": setup_type,
            "win_rate": wr,
            "sample_size": sample_size,
            "avg_r_multiple": pattern.get("avg_r_multiple", 0.0),
            "risk_flags": pattern.get("risk_flags", []),
            "avg_hold_minutes": int(
                pattern.get("avg_hold_minutes", 0)
            ),
            "confidence_bins": pattern.get("confidence_bins", {}),
        }

    def _aggregate_similar_patterns(
        self,
        similar: List[tuple],
    ) -> Dict[str, Any]:
        """Aggregate stats from multiple similar patterns."""
        total_wins = sum(p.get("win_count", 0) for _, p in similar)
        total_samples = sum(p.get("sample_size", 0) for _, p in similar)
        total_r = sum(
            p.get("avg_r_multiple", 0.0) * p.get("sample_size", 0)
            for _, p in similar
        )

        wr = total_wins / total_samples if total_samples > 0 else 0.0
        avg_r = total_r / total_samples if total_samples > 0 else 0.0

        all_risk_flags = set()
        for _, pattern in similar:
            all_risk_flags.update(pattern.get("risk_flags", []))

        return {
            "setup_type": "similar_patterns",
            "win_rate": wr,
            "sample_size": total_samples,
            "avg_r_multiple": avg_r,
            "risk_flags": list(all_risk_flags),
            "avg_hold_minutes": 0,
            "confidence_bins": {},
        }

    def _estimate_vol_adjustment(self, symbol: str) -> float:
        """Estimate volatility adjustment for symbol (1.0 = baseline).

        Higher volatility symbols need wider stops.
        Example: HYPE might be 1.5x (50% wider stops).
        """
        # Placeholder: would be computed from historical data
        # For now, hardcode based on known symbol characteristics
        vol_map = {
            "BTC": 1.0,
            "ETH": 1.1,
            "SOL": 1.3,
            "HYPE": 1.5,
        }
        return vol_map.get(symbol, 1.0)

    def _find_avoid_patterns(
        self,
        patterns: Dict[str, Dict[str, Any]],
        symbol: str,
    ) -> List[str]:
        """Find patterns with low win rates for a symbol."""
        avoid = []
        for setup_type, pattern in patterns.items():
            sample_size = pattern.get("sample_size", 0)
            win_count = pattern.get("win_count", 0)

            if sample_size >= 5:  # Minimum sample size to flag
                wr = win_count / sample_size
                if wr < 0.35:  # Less than 35% WR
                    avoid.append(setup_type)

        return avoid[:5]  # Return top 5 avoid patterns


def get_query_engine() -> DeepMemoryQuery:
    """Get or create a query engine instance."""
    return DeepMemoryQuery()
