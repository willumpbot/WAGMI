"""
Adaptive Risk-Per-Trade: dynamically adjusts risk based on streak and regime.

Instead of fixed RISK_PER_TRADE=1%, this module computes a dynamic risk
multiplier that scales position sizing based on:
1. Recent win/loss streak
2. Regime-specific win rate
3. Deep memory confidence level
"""
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger("bot.execution.adaptive_risk")

# Defaults from env
_BASE_RISK = float(os.getenv("RISK_PER_TRADE", "0.01"))  # 1%
_MIN_RISK_MULT = 0.5   # Never go below 50% of base risk
_MAX_RISK_MULT = 1.5   # Never exceed 150% of base risk

class AdaptiveRiskManager:
    """Computes dynamic risk-per-trade multiplier."""

    def __init__(self, base_risk: float = None):
        self.base_risk = base_risk or _BASE_RISK
        self._recent_outcomes: list = []  # True=win, False=loss (last 20)
        self._regime_wr: Dict[str, Dict] = {}  # {regime: {wins, total}}

    def record_outcome(self, win: bool, regime: str = ""):
        """Record a trade outcome for streak tracking."""
        self._recent_outcomes.append(win)
        if len(self._recent_outcomes) > 20:
            self._recent_outcomes = self._recent_outcomes[-20:]
        if regime:
            if regime not in self._regime_wr:
                self._regime_wr[regime] = {"wins": 0, "total": 0}
            self._regime_wr[regime]["total"] += 1
            if win:
                self._regime_wr[regime]["wins"] += 1

    def get_risk_multiplier(self, regime: str = "", symbol_wr: float = 0.0) -> float:
        """Get the adaptive risk multiplier.

        Returns a value between _MIN_RISK_MULT and _MAX_RISK_MULT.
        """
        mult = 1.0

        # Factor 1: Recent streak
        if len(self._recent_outcomes) >= 5:
            recent_5 = self._recent_outcomes[-5:]
            wins = sum(recent_5)
            if wins >= 4:
                mult *= 1.15  # 4+ wins in last 5 = boost
            elif wins >= 3:
                mult *= 1.05  # 3/5 = slight boost
            elif wins <= 1:
                mult *= 0.75  # 1 or fewer wins = reduce
            elif wins == 0:
                mult *= 0.60  # 0/5 = significant reduction

        # Factor 2: Regime-specific WR
        if regime and regime in self._regime_wr:
            rd = self._regime_wr[regime]
            if rd["total"] >= 8:
                rwr = rd["wins"] / rd["total"]
                if rwr >= 0.65:
                    mult *= 1.10  # Proven profitable regime
                elif rwr < 0.40:
                    mult *= 0.80  # Proven unprofitable regime

        # Factor 3: Symbol-specific WR (passed from feedback system)
        if symbol_wr > 0:
            if symbol_wr >= 0.65:
                mult *= 1.10  # Proven symbol
            elif symbol_wr < 0.35:
                mult *= 0.80  # Proven loser symbol

        # Clamp
        mult = max(_MIN_RISK_MULT, min(_MAX_RISK_MULT, mult))
        return round(mult, 3)

    def get_effective_risk(self, regime: str = "", symbol_wr: float = 0.0) -> float:
        """Get the actual risk-per-trade value (base * multiplier)."""
        return self.base_risk * self.get_risk_multiplier(regime, symbol_wr)

    def get_status(self) -> Dict:
        """Get current adaptive risk status for monitoring."""
        recent = self._recent_outcomes[-10:] if self._recent_outcomes else []
        return {
            "base_risk": self.base_risk,
            "recent_streak": "".join("W" if w else "L" for w in recent),
            "recent_wr": sum(recent) / len(recent) if recent else 0,
            "regime_data": {
                k: round(v["wins"] / v["total"], 2) if v["total"] > 0 else 0
                for k, v in self._regime_wr.items()
                if v["total"] >= 3
            },
        }


# Singleton
_instance: Optional[AdaptiveRiskManager] = None

def get_adaptive_risk() -> AdaptiveRiskManager:
    global _instance
    if _instance is None:
        _instance = AdaptiveRiskManager()
    return _instance
