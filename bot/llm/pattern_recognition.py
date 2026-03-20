"""
TIER 3.3: Pattern Recognition Engine

Identifies repeating setups that consistently win.

Insight: On a slow mechanical system (10 trades/day), patterns emerge:
- "Trend + 75% confidence + low volatility" wins 70% of time
- "Range + <50% confidence + high slippage" wins 35% of time

By learning patterns, LLM can:
1. Boost confidence on high-win-rate patterns
2. Reduce size on low-win-rate patterns
3. Flag when current signal matches losing pattern

Expected impact: +0.2-0.5% daily by pattern-based sizing
"""

import logging
import json
import os
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
import time
from collections import defaultdict

logger = logging.getLogger("bot.llm.pattern_recognition")


@dataclass
class Pattern:
    """A recurring setup pattern."""
    pattern_id: str
    name: str  # "Trend + High Confidence + Low Vol"

    # Pattern characteristics
    regime: Optional[str] = None
    setup_type: Optional[str] = None
    confidence_min: Optional[float] = None
    confidence_max: Optional[float] = None
    volatility_level: Optional[str] = None  # "low", "medium", "high"
    time_of_day: Optional[str] = None  # "early", "mid", "late"

    # Performance metrics
    occurrences: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0

    # Recommendations
    confidence_boost: float = 1.0  # Multiply signal confidence by this
    size_multiplier: float = 1.0  # Position size multiplier
    recommendation: str = "normal"  # "boost", "normal", "reduce", "avoid"

    # Freshness
    last_seen: float = field(default_factory=time.time)
    first_seen: float = field(default_factory=time.time)


class PatternRecognizer:
    """
    Learns patterns from historical trades and identifies them in new signals.
    """

    def __init__(self):
        """Initialize pattern recognizer."""
        self.patterns: Dict[str, Pattern] = {}
        self.pattern_counter = 0
        self.output_file = os.path.join("data/llm", "patterns.jsonl")
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load existing patterns from disk."""
        if not os.path.exists(self.output_file):
            return

        try:
            with open(self.output_file, "r") as f:
                for line in f.readlines()[-100:]:  # Load last 100 patterns
                    try:
                        data = json.loads(line.strip())
                        pattern = Pattern(
                            pattern_id=data["pattern_id"],
                            name=data["name"],
                            regime=data.get("regime"),
                            setup_type=data.get("setup_type"),
                            confidence_min=data.get("confidence_min"),
                            confidence_max=data.get("confidence_max"),
                            volatility_level=data.get("volatility_level"),
                            time_of_day=data.get("time_of_day"),
                            occurrences=data.get("occurrences", 0),
                            wins=data.get("wins", 0),
                            losses=data.get("losses", 0),
                            win_rate=data.get("win_rate", 0.0),
                            avg_pnl=data.get("avg_pnl", 0.0),
                            total_pnl=data.get("total_pnl", 0.0),
                            confidence_boost=data.get("confidence_boost", 1.0),
                            size_multiplier=data.get("size_multiplier", 1.0),
                            recommendation=data.get("recommendation", "normal"),
                        )
                        self.patterns[pattern.pattern_id] = pattern
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to load patterns: {e}")

    def discover_pattern(
        self,
        regime: str,
        setup_type: str,
        confidence: float,
        volatility_level: str,
        time_of_day: str,
    ) -> Optional[str]:
        """
        Find or create a pattern for given characteristics.

        Returns pattern_id if pattern found/created
        """
        # Create pattern key
        pattern_key = f"{regime}_{setup_type}_{int(confidence*10)}_{volatility_level}_{time_of_day}"

        # Check if pattern exists
        for p in self.patterns.values():
            if self._matches_pattern(p, regime, setup_type, confidence, volatility_level, time_of_day):
                return p.pattern_id

        # Create new pattern
        self.pattern_counter += 1
        pattern_id = f"P{self.pattern_counter}"

        pattern = Pattern(
            pattern_id=pattern_id,
            name=f"{regime} + {setup_type} ({confidence:.0%}) + {volatility_level} vol",
            regime=regime,
            setup_type=setup_type,
            confidence_min=max(0, confidence - 0.1),
            confidence_max=min(1, confidence + 0.1),
            volatility_level=volatility_level,
            time_of_day=time_of_day,
        )

        self.patterns[pattern_id] = pattern
        logger.info(f"Discovered new pattern: {pattern.name}")

        return pattern_id

    def record_pattern_outcome(
        self,
        pattern_id: str,
        win: bool,
        pnl: float,
    ) -> None:
        """Record outcome for a pattern."""
        if pattern_id not in self.patterns:
            return

        pattern = self.patterns[pattern_id]
        pattern.occurrences += 1
        pattern.total_pnl += pnl
        pattern.last_seen = time.time()

        if win:
            pattern.wins += 1
        else:
            pattern.losses += 1

        # Update metrics
        pattern.win_rate = pattern.wins / pattern.occurrences if pattern.occurrences > 0 else 0
        pattern.avg_pnl = pattern.total_pnl / pattern.occurrences if pattern.occurrences > 0 else 0

        # Update recommendations
        self._update_pattern_recommendation(pattern)

        # Persist
        self._save_pattern(pattern)

    def _update_pattern_recommendation(self, pattern: Pattern) -> None:
        """Update pattern recommendation based on performance."""
        if pattern.occurrences < 3:
            pattern.recommendation = "normal"
            pattern.confidence_boost = 1.0
            pattern.size_multiplier = 1.0
            return

        if pattern.win_rate > 0.70:
            pattern.recommendation = "boost"
            pattern.confidence_boost = 1.2
            pattern.size_multiplier = 1.3
        elif pattern.win_rate > 0.60:
            pattern.recommendation = "boost"
            pattern.confidence_boost = 1.1
            pattern.size_multiplier = 1.1
        elif pattern.win_rate > 0.50:
            pattern.recommendation = "normal"
            pattern.confidence_boost = 1.0
            pattern.size_multiplier = 1.0
        elif pattern.win_rate > 0.40:
            pattern.recommendation = "reduce"
            pattern.confidence_boost = 0.8
            pattern.size_multiplier = 0.7
        else:
            pattern.recommendation = "avoid"
            pattern.confidence_boost = 0.5
            pattern.size_multiplier = 0.3

    def _matches_pattern(
        self,
        pattern: Pattern,
        regime: str,
        setup_type: str,
        confidence: float,
        volatility_level: str,
        time_of_day: str,
    ) -> bool:
        """Check if signal matches pattern."""
        if pattern.regime and pattern.regime != regime:
            return False
        if pattern.setup_type and pattern.setup_type != setup_type:
            return False
        if pattern.volatility_level and pattern.volatility_level != volatility_level:
            return False
        if pattern.time_of_day and pattern.time_of_day != time_of_day:
            return False

        if pattern.confidence_min and confidence < pattern.confidence_min:
            return False
        if pattern.confidence_max and confidence > pattern.confidence_max:
            return False

        return True

    def get_pattern_adjustment(
        self,
        regime: str,
        setup_type: str,
        confidence: float,
        volatility_level: str,
        time_of_day: str,
    ) -> Dict[str, float]:
        """
        Get confidence/size adjustments for a signal based on pattern history.

        Returns:
            {"confidence_boost": 1.2, "size_multiplier": 1.3, "recommendation": "boost"}
        """
        pattern_id = self.discover_pattern(regime, setup_type, confidence, volatility_level, time_of_day)

        if not pattern_id or pattern_id not in self.patterns:
            return {
                "confidence_boost": 1.0,
                "size_multiplier": 1.0,
                "recommendation": "normal",
            }

        pattern = self.patterns[pattern_id]

        return {
            "confidence_boost": pattern.confidence_boost,
            "size_multiplier": pattern.size_multiplier,
            "recommendation": pattern.recommendation,
            "pattern_id": pattern_id,
            "win_rate": f"{pattern.win_rate:.0%}",
            "sample_size": pattern.occurrences,
        }

    def get_best_patterns(self, top_n: int = 5) -> List[Pattern]:
        """Get best-performing patterns."""
        # Filter patterns with minimum data
        qualified = [p for p in self.patterns.values() if p.occurrences >= 3]
        qualified.sort(key=lambda p: (p.win_rate, p.occurrences), reverse=True)
        return qualified[:top_n]

    def get_worst_patterns(self, bottom_n: int = 3) -> List[Pattern]:
        """Get worst-performing patterns."""
        qualified = [p for p in self.patterns.values() if p.occurrences >= 3]
        qualified.sort(key=lambda p: (p.win_rate, p.occurrences))
        return qualified[:bottom_n]

    def get_summary_report(self) -> Dict[str, Any]:
        """Get pattern summary."""
        if not self.patterns:
            return {"status": "no_patterns_yet"}

        total_patterns = len(self.patterns)
        total_occurrences = sum(p.occurrences for p in self.patterns.values())
        total_wins = sum(p.wins for p in self.patterns.values())
        total_pnl = sum(p.total_pnl for p in self.patterns.values())

        best = self.get_best_patterns(3)
        worst = self.get_worst_patterns(2)

        return {
            "total_patterns": total_patterns,
            "total_occurrences": total_occurrences,
            "overall_win_rate": f"{total_wins / total_occurrences:.0%}" if total_occurrences > 0 else "0%",
            "total_pnl": f"${total_pnl:+.2f}",
            "best_patterns": [
                {
                    "name": p.name,
                    "win_rate": f"{p.win_rate:.0%}",
                    "occurrences": p.occurrences,
                    "pnl": f"${p.total_pnl:+.2f}",
                    "recommendation": p.recommendation,
                }
                for p in best
            ],
            "worst_patterns": [
                {
                    "name": p.name,
                    "win_rate": f"{p.win_rate:.0%}",
                    "occurrences": p.occurrences,
                    "pnl": f"${p.total_pnl:+.2f}",
                    "recommendation": p.recommendation,
                }
                for p in worst
            ],
        }

    def _save_pattern(self, pattern: Pattern) -> None:
        """Save pattern to disk."""
        try:
            with open(self.output_file, "a") as f:
                data = {
                    "pattern_id": pattern.pattern_id,
                    "name": pattern.name,
                    "regime": pattern.regime,
                    "setup_type": pattern.setup_type,
                    "confidence_min": pattern.confidence_min,
                    "confidence_max": pattern.confidence_max,
                    "volatility_level": pattern.volatility_level,
                    "time_of_day": pattern.time_of_day,
                    "occurrences": pattern.occurrences,
                    "wins": pattern.wins,
                    "losses": pattern.losses,
                    "win_rate": pattern.win_rate,
                    "avg_pnl": pattern.avg_pnl,
                    "total_pnl": pattern.total_pnl,
                    "confidence_boost": pattern.confidence_boost,
                    "size_multiplier": pattern.size_multiplier,
                    "recommendation": pattern.recommendation,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save pattern: {e}")


# Global pattern recognizer
_global_recognizer: Optional[PatternRecognizer] = None


def get_pattern_recognizer() -> PatternRecognizer:
    """Get or create global recognizer."""
    global _global_recognizer
    if _global_recognizer is None:
        _global_recognizer = PatternRecognizer()
    return _global_recognizer
