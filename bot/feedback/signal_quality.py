"""
Signal Quality Scorer: Self-evaluating signal quality from realized outcomes.

For every signal generated, this module:
1. Predicts how good the signal is (pre-trade quality score)
2. Tracks what actually happened (post-trade outcome)
3. Learns to better predict signal quality over time
4. Feeds this back into the ensemble to weight signals dynamically

Quality dimensions:
  - Confidence accuracy: Does higher confidence actually predict wins?
  - Strategy reliability: Which strategies produce best signals right now?
  - Symbol edge: Do we have an edge on certain symbols?
  - Timing quality: Are signals at certain times better?
  - Consensus value: How much does strategy agreement matter?
  - Regime fit: Does the signal match what works in current regime?

The quality score is a meta-confidence that modulates the raw ensemble confidence.
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple

logger = logging.getLogger("bot.feedback.signal_quality")


@dataclass
class QualityFeatures:
    """Features used to predict signal quality."""
    confidence: float = 0.0
    num_strategies_agree: int = 1
    total_strategies: int = 4
    symbol: str = ""
    side: str = ""
    regime: str = ""
    entry_type: str = ""
    hour_of_day: int = 12
    day_of_week: int = 3
    volume_ratio: float = 1.0
    volatility: float = 0.0
    rr1: float = 1.0
    trend_alignment: float = 0.0
    # LLM decision data (for tracking LLM agreement → outcome correlation)
    llm_action: str = ""              # "go", "skip", "flip", "" (no LLM)
    llm_confidence: float = 0.0
    llm_agreed_with_ensemble: bool = True


class SignalQualityScorer:
    """
    Learns to predict signal quality from historical outcomes.

    Uses a simple but effective approach: track win rates across multiple
    dimensions and combine them into a quality multiplier.

    The quality score modulates confidence:
        adjusted_confidence = raw_confidence * quality_multiplier

    Where quality_multiplier ranges from 0.5 (poor quality context)
    to 1.3 (excellent quality context).
    """

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = data_dir
        self._state_file = os.path.join(data_dir, "signal_quality.json")
        os.makedirs(data_dir, exist_ok=True)

        # Dimension trackers: {key: {wins: int, total: int, pnl: float}}
        self.by_strategy: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_symbol: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_regime: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_consensus: Dict[int, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_entry_type: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_hour: Dict[int, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )
        self.by_side: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )

        # LLM agreement tracking: does LLM agreement predict wins?
        self.by_llm_agreement: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )

        # Session-level tracking (Asia/Europe/US/Late)
        self.by_session: Dict[str, Dict] = defaultdict(
            lambda: {"wins": 0, "total": 0, "pnl": 0.0, "recent": []}
        )

        # Overall quality trend
        self.overall_recent: List[int] = []  # 1=win, 0=loss, last 100

        self._load_state()

    def record_outcome(
        self,
        features: QualityFeatures,
        win: bool,
        pnl: float,
    ):
        """Record a trade outcome to update all quality dimensions."""
        result = 1 if win else 0

        def _update(tracker, key):
            d = tracker[key]
            d["total"] += 1
            if win:
                d["wins"] += 1
            d["pnl"] += pnl
            d["recent"].append(result)
            if len(d["recent"]) > 30:
                d["recent"] = d["recent"][-30:]

        _update(self.by_symbol, features.symbol)

        # Regime tracking
        if features.regime:
            _update(self.by_regime, features.regime)
        _update(self.by_consensus, features.num_strategies_agree)
        _update(self.by_entry_type, features.entry_type or "unknown")
        _update(self.by_hour, features.hour_of_day)

        # Session tracking
        session = self._hour_to_session(features.hour_of_day)
        _update(self.by_session, session)

        _update(self.by_side, features.side)

        # LLM agreement tracking
        if features.llm_action:
            agreement_key = "agreed" if features.llm_agreed_with_ensemble else "disagreed"
            _update(self.by_llm_agreement, agreement_key)

        self.overall_recent.append(result)
        if len(self.overall_recent) > 100:
            self.overall_recent = self.overall_recent[-100:]

        # Save periodically (every 10 outcomes)
        total = sum(d["total"] for d in self.by_symbol.values())
        if total % 10 == 0:
            self._save_state()

    def score_signal(self, features: QualityFeatures) -> Tuple[float, Dict[str, float]]:
        """Score a signal's quality based on historical patterns.

        Returns:
            (quality_multiplier, breakdown)

        quality_multiplier: 0.5 to 1.3
        breakdown: per-dimension scores for transparency
        """
        scores = {}
        weights = {}

        # 1. Symbol quality (how well do we trade this symbol?)
        sym_data = self.by_symbol.get(features.symbol)
        if sym_data and sym_data["total"] >= 5:
            wr = self._recent_win_rate(sym_data)
            scores["symbol"] = self._wr_to_score(wr)
            weights["symbol"] = 0.15
        else:
            scores["symbol"] = 1.0
            weights["symbol"] = 0.05  # Low weight when no data

        # 2. Regime quality (how well do we trade in this regime?)
        reg_data = self.by_regime.get(features.regime)
        if reg_data and reg_data["total"] >= 5:
            wr = self._recent_win_rate(reg_data)
            scores["regime"] = self._wr_to_score(wr)
            weights["regime"] = 0.20
        else:
            scores["regime"] = 1.0
            weights["regime"] = 0.05

        # 3. Consensus quality (does N strategies agreeing help?)
        con_data = self.by_consensus.get(features.num_strategies_agree)
        if con_data and con_data["total"] >= 5:
            wr = self._recent_win_rate(con_data)
            scores["consensus"] = self._wr_to_score(wr)
            weights["consensus"] = 0.20
        else:
            # Default: more agreement = better
            scores["consensus"] = 0.9 + features.num_strategies_agree * 0.05
            weights["consensus"] = 0.10

        # 4. Entry type quality
        et_data = self.by_entry_type.get(features.entry_type or "unknown")
        if et_data and et_data["total"] >= 5:
            wr = self._recent_win_rate(et_data)
            scores["entry_type"] = self._wr_to_score(wr)
            weights["entry_type"] = 0.15
        else:
            scores["entry_type"] = 1.0
            weights["entry_type"] = 0.05

        # 5. Time quality (is this a good hour to trade?)
        hour_data = self.by_hour.get(features.hour_of_day)
        if hour_data and hour_data["total"] >= 5:
            wr = self._recent_win_rate(hour_data)
            scores["hour"] = self._wr_to_score(wr)
            weights["hour"] = 0.10
        else:
            scores["hour"] = 1.0
            weights["hour"] = 0.03

        # 6. Side quality (are longs or shorts working better?)
        side_data = self.by_side.get(features.side)
        if side_data and side_data["total"] >= 5:
            wr = self._recent_win_rate(side_data)
            scores["side"] = self._wr_to_score(wr)
            weights["side"] = 0.10
        else:
            scores["side"] = 1.0
            weights["side"] = 0.03

        # 7. Overall system quality (is the bot performing well overall?)
        if len(self.overall_recent) >= 10:
            overall_wr = sum(self.overall_recent) / len(self.overall_recent)
            scores["overall"] = self._wr_to_score(overall_wr)
            weights["overall"] = 0.10
        else:
            scores["overall"] = 1.0
            weights["overall"] = 0.05

        # 8. LLM agreement quality (does LLM agreement predict wins?)
        if features.llm_action:
            agreement_key = "agreed" if features.llm_agreed_with_ensemble else "disagreed"
            llm_data = self.by_llm_agreement.get(agreement_key)
            if llm_data and llm_data["total"] >= 5:
                wr = self._recent_win_rate(llm_data)
                scores["llm_agreement"] = self._wr_to_score(wr)
                weights["llm_agreement"] = 0.15
            else:
                scores["llm_agreement"] = 1.0
                weights["llm_agreement"] = 0.05

        # Weighted combination
        total_weight = sum(weights.values())
        if total_weight > 0:
            quality = sum(
                scores[k] * weights[k] for k in scores
            ) / total_weight
        else:
            quality = 1.0

        # Clamp to bounds (0.5 lower lets genuinely bad signals get penalized)
        quality = max(0.5, min(1.3, quality))

        return quality, {k: round(v, 3) for k, v in scores.items()}

    def adjust_confidence(
        self, raw_confidence: float, features: QualityFeatures
    ) -> Tuple[float, float, Dict]:
        """Apply quality scoring to adjust signal confidence.

        Returns:
            (adjusted_confidence, quality_multiplier, breakdown)
        """
        quality, breakdown = self.score_signal(features)
        adjusted = raw_confidence * quality
        adjusted = max(0, min(100, adjusted))

        if abs(adjusted - raw_confidence) > 1:
            logger.info(
                f"[QUALITY] {features.symbol} {features.side}: "
                f"conf {raw_confidence:.0f}% * quality {quality:.2f} = {adjusted:.0f}% "
                f"({', '.join(f'{k}={v}' for k, v in breakdown.items() if v != 1.0)})"
            )

        return adjusted, quality, breakdown

    def _recent_win_rate(self, tracker: Dict) -> float:
        """Get recent win rate from a dimension tracker."""
        recent = tracker.get("recent", [])
        if len(recent) >= 5:
            return sum(recent) / len(recent)
        # Fall back to all-time with adaptive Bayesian prior
        total = tracker["total"]
        wins = tracker["wins"]
        # Adaptive pseudocount: stronger prior with fewer samples
        # prevents 1 loss from giving overly optimistic 0.4 quality
        pseudo = 10 if total < 5 else (5 if total < 20 else 2)
        return (wins + pseudo / 2) / (total + pseudo)

    def _wr_to_score(self, win_rate: float) -> float:
        """Convert a win rate to a quality score multiplier.

        50% win rate = 1.0 (neutral)
        75% win rate = 1.2 (boost)
        25% win rate = 0.8 (penalty)
        0%  win rate = 0.5 (harsh penalty for consistently losing)
        """
        # Linear mapping: 0% -> 0.5, 50% -> 0.9, 100% -> 1.3
        # Wider range punishes truly bad signals harder
        return 0.5 + win_rate * 0.8

    @staticmethod
    def _hour_to_session(hour: int) -> str:
        """Map hour-of-day (UTC) to trading session."""
        if 0 <= hour < 6:
            return "asia"
        elif 6 <= hour < 12:
            return "europe"
        elif 12 <= hour < 18:
            return "us"
        else:
            return "late"

    def get_report(self) -> Dict[str, Any]:
        """Get quality scoring report."""
        report = {
            "overall_recent_wr": (
                round(sum(self.overall_recent) / len(self.overall_recent), 3)
                if self.overall_recent else 0
            ),
            "total_outcomes": sum(d["total"] for d in self.by_symbol.values()),
        }

        # Top/bottom symbols
        sym_scores = {}
        for sym, data in self.by_symbol.items():
            if data["total"] >= 3:
                sym_scores[sym] = {
                    "win_rate": round(data["wins"] / data["total"], 3),
                    "recent_wr": round(self._recent_win_rate(data), 3),
                    "trades": data["total"],
                    "pnl": round(data["pnl"], 2),
                }
        report["by_symbol"] = sym_scores

        # Regime scores
        regime_scores = {}
        for regime, data in self.by_regime.items():
            if data["total"] >= 3:
                regime_scores[regime] = {
                    "win_rate": round(data["wins"] / data["total"], 3),
                    "recent_wr": round(self._recent_win_rate(data), 3),
                    "trades": data["total"],
                    "pnl": round(data["pnl"], 2),
                }
        report["by_regime"] = regime_scores

        # Consensus value
        con_scores = {}
        for n, data in sorted(self.by_consensus.items()):
            if data["total"] >= 3:
                con_scores[str(n)] = {
                    "win_rate": round(data["wins"] / data["total"], 3),
                    "trades": data["total"],
                    "pnl": round(data["pnl"], 2),
                }
        report["by_consensus"] = con_scores

        return report

    def get_symbol_confidence_floor(self, symbol: str, base_floor: float = 65.0) -> float:
        """Compute adjusted confidence floor based on symbol difficulty.

        Symbols where we consistently lose need HIGHER confidence to trade.
        Symbols where we consistently win can have LOWER floors.

        Formula: floor = base_floor * (1 + difficulty * 0.3)
        Where difficulty = 1.0 - symbol_win_rate
        """
        sym_data = self.by_symbol.get(symbol)
        if not sym_data or sym_data["total"] < 5:
            return base_floor  # Not enough data

        wr = self._recent_win_rate(sym_data)
        difficulty = 1.0 - wr
        adjusted = base_floor * (1 + difficulty * 0.3)
        # Cap: don't make floor impossibly high or too low
        adjusted = max(base_floor - 5, min(base_floor + 15, adjusted))
        return round(adjusted, 1)

    def get_session_performance(self) -> Dict[str, Any]:
        """Get per-session performance for LLM context."""
        result = {}
        for session in ("asia", "europe", "us", "late"):
            data = self.by_session.get(session)
            if data and data["total"] >= 3:
                wr = self._recent_win_rate(data)
                result[session] = {
                    "wr": round(wr * 100, 1),
                    "trades": data["total"],
                    "pnl": round(data["pnl"], 2),
                }
        return result

    def _save_state(self):
        try:
            def _serialize(tracker):
                return {
                    str(k): {
                        "wins": v["wins"],
                        "total": v["total"],
                        "pnl": v["pnl"],
                        "recent": v["recent"][-30:],
                    }
                    for k, v in tracker.items()
                }

            state = {
                "by_symbol": _serialize(self.by_symbol),
                "by_regime": _serialize(self.by_regime),
                "by_consensus": _serialize(self.by_consensus),
                "by_entry_type": _serialize(self.by_entry_type),
                "by_hour": _serialize(self.by_hour),
                "by_side": _serialize(self.by_side),
                "by_llm_agreement": _serialize(self.by_llm_agreement),
                "by_session": _serialize(self.by_session),
                "overall_recent": self.overall_recent[-100:],
            }
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save quality state: {e}")

    def _load_state(self):
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)

            def _deserialize(raw, tracker):
                for k, v in raw.items():
                    # Handle integer keys for by_consensus and by_hour
                    try:
                        key = int(k)
                    except ValueError:
                        key = k
                    tracker[key] = {
                        "wins": v["wins"],
                        "total": v["total"],
                        "pnl": v["pnl"],
                        "recent": v.get("recent", []),
                    }

            _deserialize(state.get("by_symbol", {}), self.by_symbol)
            _deserialize(state.get("by_regime", {}), self.by_regime)
            _deserialize(state.get("by_consensus", {}), self.by_consensus)
            _deserialize(state.get("by_entry_type", {}), self.by_entry_type)
            _deserialize(state.get("by_hour", {}), self.by_hour)
            _deserialize(state.get("by_side", {}), self.by_side)
            _deserialize(state.get("by_llm_agreement", {}), self.by_llm_agreement)
            _deserialize(state.get("by_session", {}), self.by_session)
            self.overall_recent = state.get("overall_recent", [])

            total = sum(d["total"] for d in self.by_symbol.values())
            logger.info(f"[QUALITY] Loaded state: {total} historical outcomes")
        except Exception as e:
            logger.warning(f"Failed to load quality state: {e}")
