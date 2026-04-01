"""
Adaptive Risk-Per-Trade: dynamically adjusts risk based on streak and regime.

Instead of fixed RISK_PER_TRADE=1%, this module computes a dynamic risk
multiplier that scales position sizing based on:
1. Recent win/loss streak
2. Regime-specific win rate
3. Deep memory confidence level
"""
import json
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger("bot.execution.adaptive_risk")

# Defaults from env
_BASE_RISK = float(os.getenv("RISK_PER_TRADE", "0.01"))  # 1%
_MIN_RISK_MULT = 0.5   # Never go below 50% of base risk
_MAX_RISK_MULT = 1.5   # Never exceed 150% of base risk
_STATE_PATH = os.path.join("data", "feedback", "adaptive_risk_state.json")

class AdaptiveRiskManager:
    """Computes dynamic risk-per-trade multiplier."""

    def __init__(self, base_risk: float = None):
        self.base_risk = base_risk or _BASE_RISK
        self._recent_outcomes: list = []  # True=win, False=loss (last 20)
        self._regime_wr: Dict[str, Dict] = {}  # {regime: {wins, total}}
        self._load_state()

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
        self._save_state()

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
            elif wins == 0:
                mult *= 0.60  # 0/5 = significant reduction (max losing streak)
            elif wins == 1:
                mult *= 0.75  # 1/5 = reduce risk

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

    def _save_state(self):
        """Persist recent outcomes and regime WR to disk."""
        try:
            os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
            state = {
                "recent_outcomes": self._recent_outcomes,
                "regime_wr": self._regime_wr,
            }
            with open(_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save adaptive risk state: {e}")

    def _load_state(self):
        """Restore persisted state from disk."""
        if not os.path.exists(_STATE_PATH):
            return
        try:
            with open(_STATE_PATH) as f:
                state = json.load(f)
            self._recent_outcomes = state.get("recent_outcomes", [])[-20:]
            self._regime_wr = state.get("regime_wr", {})
            total_outcomes = len(self._recent_outcomes)
            if total_outcomes:
                logger.info(
                    f"[ADAPTIVE_RISK] Restored state: {total_outcomes} outcomes, "
                    f"{len(self._regime_wr)} regimes tracked"
                )
        except Exception as e:
            logger.warning(f"Failed to load adaptive risk state: {e}")


# Singleton
_instance: Optional[AdaptiveRiskManager] = None

def get_adaptive_risk() -> AdaptiveRiskManager:
    global _instance
    if _instance is None:
        _instance = AdaptiveRiskManager()
    return _instance


# ─── Adaptive Sizer (Anti-Martingale) ──────────────────────────────────
# Proven quant technique: size UP when hot, size DOWN when cold.
# Data insight: larger positions show 64-73% WR vs 42-45% for smaller ones.
# Per-symbol heat tracking with floor/ceiling protection.

_ADAPTIVE_SIZER_STATE_PATH = os.path.join("data", "feedback", "adaptive_sizer_state.json")


class AdaptiveSizer:
    """Anti-martingale position sizing: size up when winning, down when losing.

    Tracks per-symbol trade outcomes in a rolling window and computes a
    'heat' score from -1.0 (ice cold) to +1.0 (on fire). The heat score
    maps linearly to a sizing multiplier between min_floor and max_boost.

    Usage:
        sizer = AdaptiveSizer(window=20, max_boost=1.5, min_floor=0.5)
        sizer.record_outcome("BTC", won=True)
        mult = sizer.get_sizing_multiplier("BTC")  # e.g. 1.25x
    """

    def __init__(
        self,
        window: int = 20,
        max_boost: float = 1.5,
        min_floor: float = 0.5,
    ):
        self.window = max(window, 3)  # minimum 3 to be meaningful
        self.max_boost = max_boost
        self.min_floor = min_floor
        # Per-symbol outcome history: {symbol: [True/False, ...]}
        self._outcomes: Dict[str, list] = {}
        self._load_state()

    def record_outcome(self, symbol: str, won: bool) -> None:
        """Record a trade outcome for a symbol.

        Args:
            symbol: Trading symbol (e.g. 'BTC', 'HYPE/USDC:USDC')
            won: Whether the trade was profitable
        """
        base = self._normalize_symbol(symbol)
        if base not in self._outcomes:
            self._outcomes[base] = []
        self._outcomes[base].append(won)
        # Keep rolling window
        if len(self._outcomes[base]) > self.window:
            self._outcomes[base] = self._outcomes[base][-self.window:]
        self._save_state()

    def get_heat(self, symbol: str) -> float:
        """Compute heat score for a symbol: -1.0 (cold) to +1.0 (hot).

        Heat formula:
          1. Base heat from recent WR: maps 40%-60% WR to -1..+1 linearly
          2. Streak bonus: consecutive wins/losses accelerate heat
          3. Clamped to [-1.0, +1.0]
        """
        base = self._normalize_symbol(symbol)
        outcomes = self._outcomes.get(base, [])

        if len(outcomes) < 3:
            return 0.0  # Not enough data — neutral

        # Recent win rate
        wins = sum(outcomes)
        total = len(outcomes)
        wr = wins / total

        # Base heat: linear map from WR to heat
        # WR 0.60 → heat +1.0, WR 0.40 → heat -1.0, WR 0.50 → heat 0.0
        base_heat = (wr - 0.50) / 0.10  # 10% WR = 1.0 heat unit

        # Streak bonus: consecutive wins/losses at tail accelerate heat
        streak = self._get_streak(outcomes)
        # Each consecutive win/loss adds 0.15 heat (up to ±0.6 from streak)
        streak_bonus = streak * 0.15
        streak_bonus = max(-0.6, min(0.6, streak_bonus))

        # Combine: 70% WR-based + 30% streak-based
        heat = base_heat * 0.7 + streak_bonus * 0.3 + streak_bonus * 0.7

        # Clamp
        return max(-1.0, min(1.0, heat))

    def get_sizing_multiplier(self, symbol: str) -> float:
        """Get the sizing multiplier for a symbol based on heat.

        Returns:
            float between min_floor and max_boost:
              heat +1.0 → max_boost (e.g. 1.5x)
              heat  0.0 → 1.0x (neutral)
              heat -1.0 → min_floor (e.g. 0.5x)
        """
        heat = self.get_heat(symbol)

        # Linear interpolation
        if heat >= 0:
            # 0.0 → 1.0x, +1.0 → max_boost
            mult = 1.0 + heat * (self.max_boost - 1.0)
        else:
            # 0.0 → 1.0x, -1.0 → min_floor
            mult = 1.0 + heat * (1.0 - self.min_floor)

        # Safety clamps
        mult = max(self.min_floor, min(self.max_boost, mult))
        return round(mult, 3)

    def get_status(self) -> Dict:
        """Get status of all tracked symbols for monitoring."""
        status = {}
        for sym, outcomes in self._outcomes.items():
            total = len(outcomes)
            wins = sum(outcomes) if outcomes else 0
            status[sym] = {
                "trades": total,
                "wr": round(wins / total, 3) if total > 0 else 0,
                "heat": round(self.get_heat(sym), 3),
                "multiplier": self.get_sizing_multiplier(sym),
                "streak": self._get_streak(outcomes),
                "recent": "".join("W" if w else "L" for w in outcomes[-10:]),
            }
        return status

    @staticmethod
    def _get_streak(outcomes: list) -> int:
        """Get current streak from tail of outcomes. Positive=wins, negative=losses."""
        if not outcomes:
            return 0
        streak = 0
        last = outcomes[-1]
        for o in reversed(outcomes):
            if o == last:
                streak += 1
            else:
                break
        return streak if last else -streak

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize symbol to base form (e.g. 'BTC/USDC:USDC' -> 'BTC')."""
        return symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")

    def _save_state(self):
        """Persist state to disk."""
        try:
            os.makedirs(os.path.dirname(_ADAPTIVE_SIZER_STATE_PATH), exist_ok=True)
            state = {"outcomes": self._outcomes, "window": self.window}
            with open(_ADAPTIVE_SIZER_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save adaptive sizer state: {e}")

    def _load_state(self):
        """Restore persisted state."""
        if not os.path.exists(_ADAPTIVE_SIZER_STATE_PATH):
            return
        try:
            with open(_ADAPTIVE_SIZER_STATE_PATH) as f:
                state = json.load(f)
            raw = state.get("outcomes", {})
            # Trim to current window size
            for sym, outs in raw.items():
                self._outcomes[sym] = outs[-self.window:]
            if self._outcomes:
                logger.info(
                    f"[ADAPTIVE_SIZER] Restored state: {len(self._outcomes)} symbols tracked"
                )
        except Exception as e:
            logger.warning(f"Failed to load adaptive sizer state: {e}")


# Singleton for AdaptiveSizer
_sizer_instance: Optional[AdaptiveSizer] = None


def get_adaptive_sizer(config=None) -> AdaptiveSizer:
    """Get or create the singleton AdaptiveSizer, configured from TradingConfig."""
    global _sizer_instance
    if _sizer_instance is None:
        window = 20
        max_boost = 1.5
        min_floor = 0.5
        if config is not None:
            window = getattr(config, "adaptive_sizing_window", 20)
            max_boost = getattr(config, "adaptive_sizing_max_boost", 1.5)
            min_floor = getattr(config, "adaptive_sizing_min_floor", 0.5)
        _sizer_instance = AdaptiveSizer(
            window=window, max_boost=max_boost, min_floor=min_floor,
        )
    return _sizer_instance
