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
import math
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
    # Strategy attribution
    strategy: str = ""  # Primary driving strategy (for per-strategy weight learning)
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

        # Symbol+side tracking (symbol-pooled PnL hides side-specific edges,
        # e.g. ETH_SHORT +$20.37/tr vs ETH_LONG -$2.28/tr) — key: "SYMBOL|SIDE"
        self.by_symbol_side: Dict[str, Dict] = defaultdict(
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
            if len(d["recent"]) > 50:
                d["recent"] = d["recent"][-50:]

        _update(self.by_symbol, features.symbol)

        # Strategy tracking (was missing — weights never learned from performance)
        if features.strategy:
            _update(self.by_strategy, features.strategy)

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
        if features.symbol and features.side:
            _update(self.by_symbol_side, f"{features.symbol}|{features.side}")

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
            scores["symbol"] = self._wr_to_score(wr, sym_data)
            weights["symbol"] = self._dimension_discriminative_power(self.by_symbol, 0.15)
        else:
            scores["symbol"] = 1.0
            weights["symbol"] = 0.05  # Low weight when no data

        # 2. Regime quality (how well do we trade in this regime?)
        reg_data = self.by_regime.get(features.regime)
        if reg_data and reg_data["total"] >= 5:
            wr = self._recent_win_rate(reg_data)
            scores["regime"] = self._wr_to_score(wr, reg_data)
            weights["regime"] = self._dimension_discriminative_power(self.by_regime, 0.20)
        else:
            scores["regime"] = 1.0
            weights["regime"] = 0.05

        # 3. Consensus quality (does N strategies agreeing help?)
        con_data = self.by_consensus.get(features.num_strategies_agree)
        if con_data and con_data["total"] >= 5:
            wr = self._recent_win_rate(con_data)
            scores["consensus"] = self._wr_to_score(wr, con_data)
            weights["consensus"] = self._dimension_discriminative_power(self.by_consensus, 0.20)
        else:
            # No live data for this bucket yet: neutral, low-weight fallback
            # (matches every other dimension's no-data fallback). The live
            # branch above (n>=5) already governs all observed buckets, and
            # realized ledger PnL says MORE agreement is NOT better here
            # (consensus=1 n=124 +$8.92/tr vs consensus=2 n=62 -$8.20/tr) —
            # do not resurrect a directional prior for unseen buckets.
            scores["consensus"] = 1.0
            weights["consensus"] = 0.05

        # 4. Entry type quality
        et_data = self.by_entry_type.get(features.entry_type or "unknown")
        if et_data and et_data["total"] >= 5:
            wr = self._recent_win_rate(et_data)
            scores["entry_type"] = self._wr_to_score(wr, et_data)
            weights["entry_type"] = self._dimension_discriminative_power(self.by_entry_type, 0.15)
        else:
            scores["entry_type"] = 1.0
            weights["entry_type"] = 0.05

        # 5. Time quality (is this a good hour to trade?)
        hour_data = self.by_hour.get(features.hour_of_day)
        if hour_data and hour_data["total"] >= 5:
            wr = self._recent_win_rate(hour_data)
            scores["hour"] = self._wr_to_score(wr, hour_data)
            weights["hour"] = self._dimension_discriminative_power(self.by_hour, 0.10)
        else:
            scores["hour"] = 1.0
            weights["hour"] = 0.03

        # 6. Side quality (are longs or shorts working better?)
        side_data = self.by_side.get(features.side)
        if side_data and side_data["total"] >= 5:
            wr = self._recent_win_rate(side_data)
            scores["side"] = self._wr_to_score(wr, side_data)
            weights["side"] = self._dimension_discriminative_power(self.by_side, 0.10)
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
                scores["llm_agreement"] = self._wr_to_score(wr, llm_data)
                weights["llm_agreement"] = self._dimension_discriminative_power(self.by_llm_agreement, 0.15)
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

    def _wr_to_score(self, win_rate: float, tracker: Dict = None) -> float:
        """Convert a win rate (+ optional pnl tracker) to a quality score multiplier.

        LIVING VALUES: the neutral baseline is the LIVE system win rate
        (overall_recent, n>=13), not a frozen 35% constant — the old frozen
        35% no longer matched realized ledger WR (43.8% overall as of
        2026-07-15) and was blanket-boosting every signal.

        When a per-dimension tracker is supplied, blend in realized
        expectancy (avg net pnl/trade, tanh-normalized to +-0.2) with the WR
        delta, because raw WR anti-correlates with $ edge in this ledger
        (e.g. SHORT 39.7% WR / +$5.67/tr vs LONG 50.0% WR / -$5.89/tr) —
        pure-WR scoring would rate the losing side above the profitable one.

        score = 1.0 + blended_delta, clamped to [0.65, 1.35].
        """
        if len(self.overall_recent) >= 13:
            baseline_wr = sum(self.overall_recent) / len(self.overall_recent)
        else:
            baseline_wr = 0.44  # realized ledger WR fallback (n<13), not 0.35
        wr_delta = win_rate - baseline_wr

        if tracker and tracker.get("total", 0) > 0:
            avg_pnl = tracker.get("pnl", 0.0) / tracker["total"]
            pnl_component = math.tanh(avg_pnl / 10.0) * 0.2
            delta = (wr_delta + pnl_component) / 2.0
        else:
            delta = wr_delta

        return max(0.65, min(1.35, 1.0 + delta))

    def _dimension_discriminative_power(self, tracker: Dict, floor: float, cap: float = 0.30) -> float:
        """Live per-dimension weight based on realized PnL spread across its buckets.

        LIVING VALUES: replaces the old hardcoded 0.10-0.20 weight tiers, which
        put the widest realized-edge dimension (side: $17.3/tr spread, up to
        $54.7/tr symbol-side) at the same or lower weight than dimensions with
        no positive bucket at all (regime). Dimensions whose buckets show a
        wider realized avg-pnl-per-trade spread get proportionally more say in
        the quality multiplier (the final weighted-average division in
        score_signal already normalizes weights, satisfying "sum to 1.0").

        Falls back to `floor` — the prior static tier value — when fewer than
        2 buckets in this tracker have total >= 13 (LIVING VALUES n-gate; not
        yet enough qualifying buckets to measure discriminative power).
        """
        avgs = [d["pnl"] / d["total"] for d in tracker.values() if d.get("total", 0) >= 13]
        if len(avgs) < 2:
            return floor
        spread = max(avgs) - min(avgs)
        return min(cap, max(floor, spread / 100.0))

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

    def get_symbol_confidence_floor(
        self, symbol: str, side: str = "", base_floor: float = 65.0
    ) -> float:
        """Compute adjusted confidence floor based on symbol (+ side) profitability.

        Uses PnL-per-trade, NOT win rate. Our system is 35% WR by design —
        WR-based difficulty would raise floors on every symbol, blocking
        profitable setups. PnL captures the actual edge (high payoff ratio).

        LIVING VALUES: side-aware. Symbol-pooled PnL can hide a losing side
        inside an overall-profitable symbol (e.g. ETH_LONG -$2.28/tr n=26
        pooled into ETH's blended average) and leave it with no floor raise.
        When the (symbol, side) tracker has enough data (n>=13), its own
        adjustment is blended in raise-only: side data can ADD a floor raise
        but can never REMOVE a raise already earned by the pooled-symbol
        data (e.g. HYPE_SHORT keeps HYPE's pooled raise until the pooled
        HYPE average itself recovers).
        """
        def _adjustment(avg_pnl: float) -> float:
            if avg_pnl > 0:
                return max(-5, -min(avg_pnl * 2, 5))  # Up to -5 floor reduction
            return min(10, min(abs(avg_pnl) * 1.5, 10))  # Up to +10 floor raise

        sym_data = self.by_symbol.get(symbol)
        pooled_adj = None
        if sym_data and sym_data["total"] >= 5:
            pooled_adj = _adjustment(sym_data.get("pnl", 0.0) / sym_data["total"])

        side_adj = None
        if side:
            side_data = self.by_symbol_side.get(f"{symbol}|{side}")
            if side_data and side_data["total"] >= 13:
                side_adj = _adjustment(side_data.get("pnl", 0.0) / side_data["total"])

        candidates = [a for a in (pooled_adj, side_adj) if a is not None]
        if not candidates:
            return base_floor  # Not enough data

        # Raise-only blend: side data can only push the floor UP relative to
        # the pooled adjustment, never down (safety — never weaken a floor
        # the pooled data already earned).
        adjustment = max(candidates)

        adjusted = base_floor + adjustment
        adjusted = max(base_floor - 5, min(base_floor + 15, adjusted))
        return round(adjusted, 1)

    def get_regime_profitability(self, regime: str) -> Dict[str, Any]:
        """Get profitability stats for a specific regime.

        Args:
            regime: Regime label (e.g. "trend", "mean_reversion", "volatile").

        Returns:
            Dict with keys:
                - win_rate: float (0.0-1.0), 0.0 if no data
                - total: int, number of trades in this regime
                - avg_pnl: float, average PnL per trade in this regime
        """
        data = self.by_regime.get(regime)
        if not data or data["total"] == 0:
            return {"win_rate": 0.0, "total": 0, "avg_pnl": 0.0}

        total = data["total"]
        wins = data["wins"]
        pnl = data["pnl"]

        return {
            "win_rate": round(wins / total, 4),
            "total": total,
            "avg_pnl": round(pnl / total, 4),
        }

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
                        "recent": v["recent"][-50:],
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
                "by_symbol_side": _serialize(self.by_symbol_side),
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
            self._backfill_from_trade_dna()
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
            _deserialize(state.get("by_symbol_side", {}), self.by_symbol_side)
            _deserialize(state.get("by_llm_agreement", {}), self.by_llm_agreement)
            _deserialize(state.get("by_session", {}), self.by_session)
            self.overall_recent = state.get("overall_recent", [])

            total = sum(d["total"] for d in self.by_symbol.values())
            logger.info(f"[QUALITY] Loaded state: {total} historical outcomes")
            # Always backfill from DNA if it has more trades than current state
            self._backfill_from_trade_dna()
        except Exception as e:
            logger.warning(f"Failed to load quality state: {e}")

    def _backfill_from_trade_dna(self):
        """Populate quality dimensions from historical trade_dna when state is sparse."""
        import datetime as _dt
        # Derive DNA path relative to data_dir's parent (data/feedback → data/llm/deep_memory/)
        _data_root = os.path.dirname(os.path.abspath(self.data_dir))
        dna_path = os.path.join(_data_root, "llm", "deep_memory", "trade_dna.json")
        if not os.path.exists(dna_path):
            return
        if not dna_path:
            return
        try:
            with open(dna_path) as f:
                data = json.load(f)
            trades = data.get("trades", [])
            if not trades:
                return
            current_total = sum(d["total"] for d in self.by_symbol.values())
            if len(trades) <= current_total:
                return  # Already have more data than DNA
            # Rebuild all trackers from DNA
            for tracker in [self.by_symbol, self.by_regime, self.by_consensus,
                             self.by_entry_type, self.by_hour, self.by_side,
                             self.by_symbol_side, self.by_session, self.by_llm_agreement]:
                tracker.clear()
            self.overall_recent.clear()
            for t in trades:
                win = t.get("outcome") == "WIN"
                pnl = float(t.get("pnl") or 0)
                # Derive hour from timestamp
                ts = t.get("timestamp") or t.get("entry_time") or 0
                try:
                    hour = _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).hour
                except Exception:
                    hour = 12
                features = QualityFeatures(
                    confidence=float(t.get("confidence") or 0),
                    num_strategies_agree=int(t.get("num_agree") or 1),
                    total_strategies=4,
                    symbol=(t.get("symbol") or "").replace("/USDC:USDC", "").replace("/USDT:USDT", ""),
                    side=t.get("side") or "",
                    regime=t.get("regime") or t.get("market_regime") or "",
                    entry_type=t.get("entry_type") or "",
                    hour_of_day=hour,
                    llm_action=t.get("llm_action") or "",
                    llm_confidence=float(t.get("llm_confidence") or 0),
                )
                self.record_outcome(features, win=win, pnl=pnl)
            # Skip periodic save inside record_outcome — save once at end
            self._save_state()
            total = sum(d["total"] for d in self.by_symbol.values())
            logger.info(f"[QUALITY] Backfilled {len(trades)} trades from DNA → {total} dimension entries")
        except Exception as e:
            logger.warning(f"[QUALITY] Backfill error: {e}")
