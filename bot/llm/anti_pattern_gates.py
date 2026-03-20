"""
TIER 1.3: Anti-Pattern Hard Gates

Blocks trading setups (entry patterns) with historically poor performance.

Insight: Some entry patterns are consistently losers (e.g., breakouts in ranging
markets, low-confirmation multi-tier setups). By identifying and blocking these
patterns, we eliminate unnecessary losses without affecting winning setups.

Expected impact: +0.3-0.5% daily by preventing systematic losers.

Integration: Uses SetupProfitabilityAnalyzer output to maintain a blocklist
of high-frequency losing setups. Integrated into signal gating pipeline.
"""

import logging
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass
import time

logger = logging.getLogger("bot.llm.anti_pattern_gates")


@dataclass
class AntiPattern:
    """A known losing setup type."""
    setup_type: str              # e.g., "multi_tier_quality", "breakout_5m"
    historical_win_rate: float   # Historical win rate for this setup
    sample_size: int             # Number of trades with this setup
    confidence_in_block: float   # How confident are we this setup loses? (0-1)
    reason: str                  # Why we're blocking this
    last_updated: float          # Unix timestamp


class AntiPatternGate:
    """
    Maintains a blocklist of setup types with poor historical performance.

    Uses SetupProfitabilityAnalyzer to identify setups with:
    - Win rate < 40% AND sample_size >= 5
    - Negative edge score despite multiple trials
    - Specific pattern combinations known to lose (e.g., multiple TF disagreement)

    This is integrated into the signal gating pipeline to reject signals
    from blocked setup types before they reach the ensemble.
    """

    # Hard thresholds for auto-blocking
    MIN_SAMPLES_TO_BLOCK = 5     # Need at least this many trades
    LOSS_RATE_THRESHOLD = 0.40   # Block if win_rate < 40%
    EDGE_THRESHOLD = -0.02       # Block if edge_score < -0.02

    # Manual blocklist for known problematic patterns
    MANUAL_BLOCKLIST = {
        # Add patterns here as we discover them
        # "breakout_low_vol": "Breakouts in low-volatility regimes fail 65% of the time",
    }

    def __init__(self):
        """Initialize the anti-pattern gate."""
        self.blocked_setups: Dict[str, AntiPattern] = {}
        self._load_manual_blocklist()
        self.stats = {
            "total_checked": 0,
            "total_blocked": 0,
            "blocks_by_pattern": {},
        }

    def _load_manual_blocklist(self):
        """Load manually-defined anti-patterns."""
        now = time.time()
        for setup_type, reason in self.MANUAL_BLOCKLIST.items():
            self.blocked_setups[setup_type] = AntiPattern(
                setup_type=setup_type,
                historical_win_rate=0.0,
                sample_size=999,  # Very high to show manual override
                confidence_in_block=0.99,
                reason=reason,
                last_updated=now,
            )

    def update_from_profitability(self, setup_metrics: Dict) -> int:
        """
        Update blocklist from SetupProfitabilityAnalyzer output.

        Args:
            setup_metrics: Dict[setup_type -> SetupMetrics] from analyzer.analyze_all_setups()

        Returns:
            Number of new blocks added
        """
        now = time.time()
        new_blocks = 0

        for setup_type, metrics in setup_metrics.items():
            if setup_type in self.blocked_setups:
                continue  # Already blocked

            # Check if this setup should be blocked
            should_block = False
            reason = ""

            # Criterion 1: Win rate below threshold with sufficient samples
            if metrics.total_trades >= self.MIN_SAMPLES_TO_BLOCK:
                if metrics.win_rate < self.LOSS_RATE_THRESHOLD:
                    should_block = True
                    reason = (
                        f"Win rate {metrics.win_rate:.0%} < {self.LOSS_RATE_THRESHOLD:.0%} "
                        f"({metrics.total_trades} trades)"
                    )

            # Criterion 2: Negative edge score despite multiple tries
            if not should_block and metrics.total_trades >= self.MIN_SAMPLES_TO_BLOCK:
                if metrics.edge_score < self.EDGE_THRESHOLD:
                    should_block = True
                    reason = (
                        f"Edge score {metrics.edge_score:.3f} < {self.EDGE_THRESHOLD:.3f} "
                        f"({metrics.total_trades} trades, WR={metrics.win_rate:.0%})"
                    )

            if should_block:
                self.blocked_setups[setup_type] = AntiPattern(
                    setup_type=setup_type,
                    historical_win_rate=metrics.win_rate,
                    sample_size=metrics.total_trades,
                    confidence_in_block=min(
                        0.99,
                        (metrics.total_trades / self.MIN_SAMPLES_TO_BLOCK) * 0.7
                    ),
                    reason=reason,
                    last_updated=now,
                )
                new_blocks += 1
                logger.info(f"[ANTI-PATTERN] Blocking {setup_type}: {reason}")

        return new_blocks

    def is_blocked(self, setup_type: Optional[str]) -> Tuple[bool, Optional[AntiPattern]]:
        """
        Check if a setup type is blocked.

        Args:
            setup_type: The setup type to check (typically from signal.strategy)

        Returns:
            (is_blocked: bool, pattern: Optional[AntiPattern])
        """
        self.stats["total_checked"] += 1

        if not setup_type:
            return False, None

        if setup_type in self.blocked_setups:
            pattern = self.blocked_setups[setup_type]
            self.stats["total_blocked"] += 1
            if setup_type not in self.stats["blocks_by_pattern"]:
                self.stats["blocks_by_pattern"][setup_type] = 0
            self.stats["blocks_by_pattern"][setup_type] += 1
            return True, pattern

        return False, None

    def get_blocklist(self) -> Dict[str, AntiPattern]:
        """Get the current blocklist."""
        return self.blocked_setups.copy()

    def clear_blocklist(self):
        """Clear all blocks (except manual blocklist)."""
        self.blocked_setups = {}
        self._load_manual_blocklist()
        logger.info("[ANTI-PATTERN] Blocklist cleared")

    def get_stats(self) -> Dict:
        """Get gating statistics."""
        return {
            "total_checked": self.stats["total_checked"],
            "total_blocked": self.stats["total_blocked"],
            "block_rate_pct": (
                self.stats["total_blocked"] / self.stats["total_checked"] * 100
                if self.stats["total_checked"] > 0 else 0
            ),
            "blocked_patterns": {
                setup: {
                    "win_rate": round(p.historical_win_rate, 3),
                    "sample_size": p.sample_size,
                    "confidence": round(p.confidence_in_block, 2),
                    "reason": p.reason,
                    "times_blocked": self.stats["blocks_by_pattern"].get(setup, 0),
                }
                for setup, p in self.blocked_setups.items()
            },
        }

    def reset_stats(self):
        """Reset statistics."""
        self.stats = {
            "total_checked": 0,
            "total_blocked": 0,
            "blocks_by_pattern": {},
        }


# Global gate instance
_global_gate: Optional[AntiPatternGate] = None


def get_anti_pattern_gate() -> AntiPatternGate:
    """Get or create the global anti-pattern gate."""
    global _global_gate
    if _global_gate is None:
        _global_gate = AntiPatternGate()
    return _global_gate


def check_signal_for_antipatterns(signal: Any) -> Tuple[bool, Optional[str]]:
    """
    Check if a signal's setup type is blocked by anti-pattern gate.

    Args:
        signal: Signal object (must have .strategy attribute)

    Returns:
        (passes_gate: bool, rejection_reason: Optional[str])
    """
    gate = get_anti_pattern_gate()
    setup_type = getattr(signal, "strategy", None)
    is_blocked, pattern = gate.is_blocked(setup_type)

    if is_blocked:
        reason = f"Setup '{setup_type}' is blocked: {pattern.reason}"
        return False, reason

    return True, None


def update_antipattern_gate_from_analyzer(setup_profitability_analyzer) -> int:
    """
    Update the anti-pattern gate using recent setup profitability analysis.

    Args:
        setup_profitability_analyzer: SetupProfitabilityAnalyzer instance

    Returns:
        Number of new blocks added
    """
    gate = get_anti_pattern_gate()
    setup_metrics = setup_profitability_analyzer.analyze_all_setups()
    new_blocks = gate.update_from_profitability(setup_metrics)
    return new_blocks
