"""
Regime-Aware Feedback Splitting

The 100-day backtest showed a massive performance gap between regimes:
- Trending: 100% win rate, highly profitable
- Ranging: 24% win rate, lost $29K

Yet the feedback loop applies ONE global confidence floor, ONE set of parameters.
This module splits feedback tracking by regime so that:
- Trending regime gets optimized for trend capture (lower floor, wider targets)
- Ranging regime gets optimized for selectivity (higher floor, tighter stops)
- Volatile regime gets optimized for risk management (wider stops, smaller size)
- Panic regime gets optimized for reversal detection (extreme oversold entries only)

Each regime maintains its own:
1. Confidence floor (adaptive per regime)
2. Win rate tracking
3. Optimal strategy weights
4. Risk multiplier adjustment
5. Recommended hold time

This feeds into the ensemble, leverage manager, and LLM agent prompts.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.regime_feedback")


class RegimeStats:
    """Statistics for a single regime."""

    def __init__(self, regime: str):
        self.regime = regime
        self.trades: List[Dict] = []
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0.0
        self.avg_hold_hours = 0.0
        self.confidence_floor = 65.0  # Default per-regime floor
        self.risk_multiplier = 1.0
        self.strategy_weights: Dict[str, float] = {}
        self.last_updated: Optional[str] = None

    @property
    def total_trades(self) -> int:
        return self.win_count + self.loss_count

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.5  # Prior
        return self.win_count / self.total_trades

    @property
    def avg_pnl(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t["pnl"] for t in self.trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.trades if t.get("pnl", 0) < 0))
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    def record_trade(self, pnl: float, confidence: float, strategy: str,
                     hold_hours: float = 0.0, metadata: Optional[Dict] = None):
        """Record a completed trade in this regime."""
        is_win = pnl > 0
        if is_win:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.total_pnl += pnl

        self.trades.append({
            "pnl": pnl,
            "confidence": confidence,
            "strategy": strategy,
            "hold_hours": hold_hours,
            "is_win": is_win,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        })

        # Keep only recent trades (rolling window)
        if len(self.trades) > 200:
            self.trades = self.trades[-200:]

        # Update adaptive parameters
        self._update_parameters()

    def _update_parameters(self):
        """Recompute regime-specific parameters from recent trade data."""
        if self.total_trades < 5:
            return  # Not enough data

        recent = self.trades[-50:] if len(self.trades) >= 50 else self.trades
        recent_wins = sum(1 for t in recent if t["is_win"])
        recent_wr = recent_wins / len(recent) if recent else 0.5

        # Adaptive confidence floor based on win rate
        if recent_wr >= 0.65:
            # Profitable regime: can afford lower floor
            self.confidence_floor = max(55.0, 65.0 - (recent_wr - 0.65) * 30)
        elif recent_wr >= 0.45:
            # Marginal regime: moderate floor
            self.confidence_floor = 70.0
        else:
            # Losing regime: high floor to filter
            self.confidence_floor = min(90.0, 75.0 + (0.45 - recent_wr) * 50)

        # Risk multiplier based on win rate
        if recent_wr >= 0.60:
            self.risk_multiplier = min(1.3, 1.0 + (recent_wr - 0.60) * 1.0)
        elif recent_wr >= 0.40:
            self.risk_multiplier = 1.0
        else:
            self.risk_multiplier = max(0.4, 1.0 - (0.40 - recent_wr) * 2.0)

        # Strategy weights: which strategies perform best in this regime?
        strat_wins: Dict[str, int] = {}
        strat_total: Dict[str, int] = {}
        for t in recent:
            s = t.get("strategy", "unknown")
            strat_total[s] = strat_total.get(s, 0) + 1
            if t["is_win"]:
                strat_wins[s] = strat_wins.get(s, 0) + 1

        for s, total in strat_total.items():
            if total >= 3:
                wr = strat_wins.get(s, 0) / total
                self.strategy_weights[s] = wr

        # Average hold time
        hold_times = [t.get("hold_hours", 0) for t in recent if t.get("hold_hours", 0) > 0]
        if hold_times:
            self.avg_hold_hours = sum(hold_times) / len(hold_times)

        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor if self.profit_factor != float("inf") else 999.0,
            "confidence_floor": self.confidence_floor,
            "risk_multiplier": self.risk_multiplier,
            "avg_hold_hours": self.avg_hold_hours,
            "strategy_weights": self.strategy_weights,
            "last_updated": self.last_updated,
            "recent_trades_count": len(self.trades),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RegimeStats":
        rs = cls(d["regime"])
        rs.win_count = d.get("win_count", 0)
        rs.loss_count = d.get("loss_count", 0)
        rs.total_pnl = d.get("total_pnl", 0.0)
        rs.confidence_floor = d.get("confidence_floor", 65.0)
        rs.risk_multiplier = d.get("risk_multiplier", 1.0)
        rs.avg_hold_hours = d.get("avg_hold_hours", 0.0)
        rs.strategy_weights = d.get("strategy_weights", {})
        rs.last_updated = d.get("last_updated")
        return rs


# Default regime presets (before any data is collected)
REGIME_PRESETS = {
    "trend": {"confidence_floor": 60.0, "risk_multiplier": 1.2,
              "description": "Strong edge, allow more trades"},
    "range": {"confidence_floor": 85.0, "risk_multiplier": 0.6,
              "description": "Weak edge, filter aggressively"},
    "panic": {"confidence_floor": 80.0, "risk_multiplier": 0.5,
              "description": "Extreme caution, reversal only"},
    "high_volatility": {"confidence_floor": 75.0, "risk_multiplier": 0.7,
                        "description": "Wide stops, smaller size"},
    "low_liquidity": {"confidence_floor": 90.0, "risk_multiplier": 0.3,
                      "description": "Almost no trades, extreme filter"},
    "news_dislocation": {"confidence_floor": 80.0, "risk_multiplier": 0.5,
                         "description": "Fast moves, caution"},
    "unknown": {"confidence_floor": 80.0, "risk_multiplier": 0.7,
                "description": "Uncertain, conservative default"},
}


class RegimeFeedbackManager:
    """
    Maintains per-regime feedback loops with independent parameter tuning.

    Each regime gets its own confidence floor, risk multiplier, and strategy
    weight recommendations based on observed performance in that regime.
    """

    KNOWN_REGIMES = ["trend", "range", "panic", "high_volatility",
                     "low_liquidity", "news_dislocation", "unknown"]

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "regime_feedback_state.json"

        self.regimes: Dict[str, RegimeStats] = {}
        self._init_regimes()
        self._load()

    def _init_regimes(self):
        """Initialize regime stats with presets."""
        for regime in self.KNOWN_REGIMES:
            stats = RegimeStats(regime)
            preset = REGIME_PRESETS.get(regime, {})
            stats.confidence_floor = preset.get("confidence_floor", 70.0)
            stats.risk_multiplier = preset.get("risk_multiplier", 1.0)
            self.regimes[regime] = stats

    def _load(self):
        """Load persisted regime feedback state."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            for regime_name, regime_data in data.items():
                if regime_name in self.regimes:
                    loaded = RegimeStats.from_dict(regime_data)
                    # Preserve any accumulated trade data
                    loaded.trades = self.regimes[regime_name].trades
                    self.regimes[regime_name] = loaded
        except Exception as e:
            logger.warning(f"Failed to load regime feedback state: {e}")

    def _save(self):
        """Persist regime feedback state."""
        try:
            data = {name: stats.to_dict() for name, stats in self.regimes.items()}
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save regime feedback state: {e}")

    def record_trade(self, regime: str, pnl: float, confidence: float,
                     strategy: str, hold_hours: float = 0.0,
                     metadata: Optional[Dict] = None):
        """Record a trade outcome under its regime."""
        # Normalize regime name
        regime = regime.lower().strip()
        if regime not in self.regimes:
            regime = "unknown"

        self.regimes[regime].record_trade(pnl, confidence, strategy,
                                           hold_hours, metadata)
        self._save()

    def get_confidence_floor(self, regime: str) -> float:
        """Get the adaptive confidence floor for a regime."""
        regime = regime.lower().strip()
        stats = self.regimes.get(regime)
        if stats is None:
            return REGIME_PRESETS.get("unknown", {}).get("confidence_floor", 75.0)
        return stats.confidence_floor

    def get_risk_multiplier(self, regime: str) -> float:
        """Get the risk multiplier for a regime."""
        regime = regime.lower().strip()
        stats = self.regimes.get(regime)
        if stats is None:
            return REGIME_PRESETS.get("unknown", {}).get("risk_multiplier", 0.7)
        return stats.risk_multiplier

    def get_strategy_weights(self, regime: str) -> Dict[str, float]:
        """Get per-strategy weights optimized for this regime."""
        regime = regime.lower().strip()
        stats = self.regimes.get(regime)
        if stats is None:
            return {}
        return stats.strategy_weights

    def get_regime_summary(self) -> Dict[str, Dict]:
        """Get summary of all regime performance stats."""
        return {name: stats.to_dict() for name, stats in self.regimes.items()}

    def get_prompt_context(self, current_regime: str) -> str:
        """Generate context for LLM agent prompts about regime-specific performance."""
        regime = current_regime.lower().strip()
        stats = self.regimes.get(regime)
        if stats is None or stats.total_trades < 3:
            preset = REGIME_PRESETS.get(regime, {})
            return f"REGIME FEEDBACK: {regime} — {preset.get('description', 'no data')}, floor={preset.get('confidence_floor', 75)}%"

        lines = [f"REGIME FEEDBACK ({regime}, {stats.total_trades} trades):"]
        lines.append(f"  Win rate: {stats.win_rate*100:.0f}% | PF: {stats.profit_factor:.2f} | Avg PnL: {stats.avg_pnl:+.2f}%")
        lines.append(f"  Confidence floor: {stats.confidence_floor:.0f}% | Risk mult: {stats.risk_multiplier:.2f}x")

        if stats.strategy_weights:
            best = sorted(stats.strategy_weights.items(), key=lambda x: -x[1])[:3]
            best_str = ", ".join(f"{s}={w*100:.0f}%" for s, w in best)
            lines.append(f"  Best strategies: {best_str}")

        if stats.avg_hold_hours > 0:
            lines.append(f"  Avg hold: {stats.avg_hold_hours:.1f}h")

        # Cross-regime comparison
        all_wrs = {n: s.win_rate for n, s in self.regimes.items() if s.total_trades >= 5}
        if len(all_wrs) >= 2:
            best_regime = max(all_wrs, key=all_wrs.get)
            worst_regime = min(all_wrs, key=all_wrs.get)
            if best_regime != worst_regime:
                lines.append(f"  Best regime: {best_regime} ({all_wrs[best_regime]*100:.0f}% WR) | "
                             f"Worst: {worst_regime} ({all_wrs[worst_regime]*100:.0f}% WR)")

        return "\n".join(lines)

    def get_regime_recommendation(self, regime: str) -> Dict[str, Any]:
        """Get trading recommendations specific to this regime."""
        regime = regime.lower().strip()
        stats = self.regimes.get(regime)

        if stats is None or stats.total_trades < 5:
            preset = REGIME_PRESETS.get(regime, REGIME_PRESETS["unknown"])
            return {
                "confidence_floor": preset["confidence_floor"],
                "risk_multiplier": preset["risk_multiplier"],
                "data_source": "preset",
                "recommendation": preset.get("description", "insufficient data"),
            }

        return {
            "confidence_floor": stats.confidence_floor,
            "risk_multiplier": stats.risk_multiplier,
            "strategy_weights": stats.strategy_weights,
            "win_rate": stats.win_rate,
            "profit_factor": stats.profit_factor,
            "avg_hold_hours": stats.avg_hold_hours,
            "data_source": "adaptive",
            "trades_observed": stats.total_trades,
        }
