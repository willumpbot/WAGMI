"""
Meta-Learning Engine — LLM self-analysis and strategy idea generation.

This module enables the system to analyze its own decision patterns and
auto-generate strategy hypotheses based on observed statistical edges.

Two key capabilities:

1. **LLM Meta-Analysis**: Review trading history and identify patterns
   in decisions — time-of-day biases, regime biases, confidence
   calibration, strategy clustering, sizing patterns, veto correlations.

2. **Strategy Idea Generation**: Based on observed patterns, generate
   concrete, testable hypotheses for new strategy parameters or filters.

All analysis is done locally via pure statistical computation (no LLM API
calls). Pattern detection uses simple statistical tests over stdlib math.

Data persistence:
  - Insights stored in   data/meta_learning/insights.json
  - Ideas stored in      data/meta_learning/ideas.json
  - Tick state stored in data/meta_learning/tick_state.json

Usage:
    from analytics.meta_learning import get_meta_engine
    engine = get_meta_engine()
    engine.tick(recent_trades=trades, market_state=state)
    print(engine.get_meta_report())
"""

import json
import logging
import math
import os
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.meta_learning")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MetaInsight:
    """A pattern or bias discovered through meta-analysis."""
    category: str           # "pattern", "bias", "edge", "weakness"
    description: str
    confidence: float       # 0-1
    evidence_count: int
    actionable_suggestion: str
    timestamp: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MetaInsight":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class StrategyIdea:
    """A generated strategy idea derived from meta-insights."""
    id: str
    name: str
    description: str
    trigger_condition: str      # e.g. "When BTC regime is 'trending' and funding > 0.01%"
    parameters: Dict[str, Any]  # Suggested parameter overrides
    expected_edge: str
    source_pattern: str         # What data pattern led to this idea
    status: str = "proposed"    # proposed, testing, validated, rejected
    test_results: Dict = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyIdea":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Statistics helpers (stdlib only, no numpy)
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> float:
    """Arithmetic mean, returns 0.0 for empty list."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    """Population standard deviation, returns 0.0 for < 2 values."""
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    variance = sum((x - mu) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _win_rate(trades: List[Dict]) -> float:
    """Win rate from a list of trade dicts (pnl > 0 = win)."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _parse_float(t.get("pnl", 0)) > 0)
    return wins / len(trades)


def _avg_pnl(trades: List[Dict]) -> float:
    """Average PnL from a list of trade dicts."""
    if not trades:
        return 0.0
    return _mean([_parse_float(t.get("pnl", 0)) for t in trades])


def _median(values: List[float]) -> float:
    """Median of a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def _pearson_r(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 if insufficient data."""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _parse_float(val) -> float:
    """Safely parse a value to float."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_trade_ts(trade: Dict) -> float:
    """Extract timestamp from a trade row."""
    for key in ("timestamp", "ts", "close_ts", "open_ts", "time"):
        val = trade.get(key, "")
        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                try:
                    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                    return dt.timestamp()
                except (ValueError, TypeError):
                    continue
    return 0.0


# ---------------------------------------------------------------------------
# Time bucket helpers
# ---------------------------------------------------------------------------

_TIME_BUCKETS = {
    "night":     (0, 6),    # 00:00 - 05:59 UTC
    "morning":   (6, 12),   # 06:00 - 11:59 UTC
    "afternoon": (12, 18),  # 12:00 - 17:59 UTC
    "evening":   (18, 24),  # 18:00 - 23:59 UTC
}


def _hour_to_bucket(hour: int) -> str:
    """Map UTC hour to a time bucket name."""
    for name, (lo, hi) in _TIME_BUCKETS.items():
        if lo <= hour < hi:
            return name
    return "night"


# ---------------------------------------------------------------------------
# MetaLearningEngine
# ---------------------------------------------------------------------------

class MetaLearningEngine:
    """Analyzes the bot's own decision patterns and generates strategy ideas.

    All analysis is pure statistical computation — no LLM API calls.
    Thread-safe via an internal lock for state mutations.
    """

    def __init__(self, data_dir: str = "data/meta_learning"):
        self.data_dir = data_dir
        self._insights_path = os.path.join(data_dir, "insights.json")
        self._ideas_path = os.path.join(data_dir, "ideas.json")
        self._tick_state_path = os.path.join(data_dir, "tick_state.json")

        self._insights: List[MetaInsight] = []
        self._ideas: List[StrategyIdea] = []
        self._tick_state: Dict[str, Any] = {
            "last_tick_ts": 0.0,
            "total_ticks": 0,
        }

        self._lock = threading.Lock()
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _ensure_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        self._ensure_dir()
        self._load_insights()
        self._load_ideas()
        self._load_tick_state()

    def _load_insights(self):
        if not os.path.exists(self._insights_path):
            return
        try:
            with open(self._insights_path, "r") as f:
                data = json.load(f)
            self._insights = [
                MetaInsight.from_dict(d) for d in data.get("insights", [])
            ]
            logger.info(
                f"[META] Loaded {len(self._insights)} historical insights"
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[META] Failed to load insights: {e}")

    def _save_insights(self):
        self._ensure_dir()
        # Keep the most recent 200 insights
        if len(self._insights) > 200:
            self._insights = sorted(
                self._insights, key=lambda i: i.timestamp, reverse=True
            )[:200]
        try:
            with open(self._insights_path, "w") as f:
                json.dump(
                    {"insights": [i.to_dict() for i in self._insights]},
                    f, indent=2, default=str,
                )
        except IOError as e:
            logger.warning(f"[META] Failed to save insights: {e}")

    def _load_ideas(self):
        if not os.path.exists(self._ideas_path):
            return
        try:
            with open(self._ideas_path, "r") as f:
                data = json.load(f)
            self._ideas = [
                StrategyIdea.from_dict(d) for d in data.get("ideas", [])
            ]
            logger.info(
                f"[META] Loaded {len(self._ideas)} strategy ideas"
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"[META] Failed to load ideas: {e}")

    def _save_ideas(self):
        self._ensure_dir()
        # Keep the most recent 100 ideas
        if len(self._ideas) > 100:
            active = [i for i in self._ideas if i.status in ("proposed", "testing")]
            settled = sorted(
                [i for i in self._ideas if i.status in ("validated", "rejected")],
                key=lambda i: i.updated_at, reverse=True,
            )[:50]
            self._ideas = active + settled
        try:
            with open(self._ideas_path, "w") as f:
                json.dump(
                    {"ideas": [i.to_dict() for i in self._ideas]},
                    f, indent=2, default=str,
                )
        except IOError as e:
            logger.warning(f"[META] Failed to save ideas: {e}")

    def _load_tick_state(self):
        if not os.path.exists(self._tick_state_path):
            return
        try:
            with open(self._tick_state_path, "r") as f:
                self._tick_state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    def _save_tick_state(self):
        self._ensure_dir()
        try:
            with open(self._tick_state_path, "w") as f:
                json.dump(self._tick_state, f, indent=2)
        except IOError as e:
            logger.warning(f"[META] Failed to save tick state: {e}")

    # ------------------------------------------------------------------
    # Core analysis: analyze_decision_patterns
    # ------------------------------------------------------------------

    def analyze_decision_patterns(
        self,
        recent_trades: List[Dict],
        lookback_days: int = 14,
    ) -> List[MetaInsight]:
        """Analyze recent trading decisions for patterns.

        Looks for:
        - Time-of-day biases (do we trade worse at certain hours?)
        - Regime biases (do we overtrade in choppy markets?)
        - Confidence calibration (are 90%+ signals actually 90% WR?)
        - Strategy clustering (do we rely too much on one strategy?)
        - Sizing patterns (do large positions do worse?)
        - Veto patterns (are vetoes correlated with later price action?)

        Args:
            recent_trades: List of trade dicts with keys like pnl, timestamp,
                confidence, strategy, regime, side, leverage, etc.
            lookback_days: Only consider trades within this window.

        Returns:
            List of MetaInsight objects describing discovered patterns.
        """
        with self._lock:
            self._ensure_loaded()

        if not recent_trades:
            return []

        # Filter to lookback window
        cutoff = time.time() - (lookback_days * 86400)
        trades = [
            t for t in recent_trades
            if _parse_trade_ts(t) > cutoff or _parse_trade_ts(t) == 0
        ]

        if len(trades) < 5:
            logger.debug("[META] Not enough trades for pattern analysis")
            return []

        insights: List[MetaInsight] = []
        now = time.time()

        # --- 1. Time-of-day bias ---
        insights.extend(self._analyze_time_of_day(trades, now))

        # --- 2. Regime bias ---
        insights.extend(self._analyze_regime_bias(trades, now))

        # --- 3. Confidence calibration ---
        insights.extend(self._analyze_confidence_calibration(trades, now))

        # --- 4. Strategy clustering ---
        insights.extend(self._analyze_strategy_clustering(trades, now))

        # --- 5. Sizing patterns ---
        insights.extend(self._analyze_sizing_patterns(trades, now))

        # --- 6. Veto patterns ---
        insights.extend(self._analyze_veto_patterns(trades, now))

        # --- 7. Side bias ---
        insights.extend(self._analyze_side_bias(trades, now))

        # --- 8. Consecutive loss streaks ---
        insights.extend(self._analyze_streak_patterns(trades, now))

        # Store new insights
        with self._lock:
            self._insights.extend(insights)
            self._save_insights()

        if insights:
            logger.info(
                f"[META] Discovered {len(insights)} insights from "
                f"{len(trades)} trades"
            )

        return insights

    # ------------------------------------------------------------------
    # Pattern detectors
    # ------------------------------------------------------------------

    def _analyze_time_of_day(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Compare win rates across 4 time buckets."""
        insights = []
        buckets: Dict[str, List[Dict]] = defaultdict(list)

        for t in trades:
            ts = _parse_trade_ts(t)
            if ts <= 0:
                continue
            hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
            bucket = _hour_to_bucket(hour)
            buckets[bucket].append(t)

        overall_wr = _win_rate(trades)
        bucket_wrs: Dict[str, Tuple[float, int]] = {}

        for bucket_name, bucket_trades in buckets.items():
            if len(bucket_trades) < 3:
                continue
            wr = _win_rate(bucket_trades)
            bucket_wrs[bucket_name] = (wr, len(bucket_trades))

        if len(bucket_wrs) < 2:
            return insights

        # Identify best and worst buckets
        best_bucket = max(bucket_wrs, key=lambda b: bucket_wrs[b][0])
        worst_bucket = min(bucket_wrs, key=lambda b: bucket_wrs[b][0])

        best_wr, best_n = bucket_wrs[best_bucket]
        worst_wr, worst_n = bucket_wrs[worst_bucket]

        # Significant difference: > 15pp spread with enough samples
        spread = best_wr - worst_wr
        if spread > 0.15 and best_n >= 3 and worst_n >= 3:
            lo, hi = _TIME_BUCKETS[best_bucket]
            insights.append(MetaInsight(
                category="pattern",
                description=(
                    f"Time-of-day edge: '{best_bucket}' ({lo}:00-{hi}:00 UTC) "
                    f"wins {best_wr:.0%} vs '{worst_bucket}' at {worst_wr:.0%} "
                    f"(spread: {spread:.0%})"
                ),
                confidence=min(0.85, 0.4 + (best_n + worst_n) / 60),
                evidence_count=best_n + worst_n,
                actionable_suggestion=(
                    f"Boost confidence for trades during {best_bucket} "
                    f"({lo}:00-{hi}:00 UTC). Consider raising confidence "
                    f"floor during {worst_bucket} by 5-10%."
                ),
                timestamp=now,
            ))

        # Check if a single bucket is dragging down performance
        if worst_wr < 0.35 and worst_n >= 5:
            lo, hi = _TIME_BUCKETS[worst_bucket]
            insights.append(MetaInsight(
                category="weakness",
                description=(
                    f"Significant time-of-day weakness: '{worst_bucket}' "
                    f"({lo}:00-{hi}:00 UTC) has only {worst_wr:.0%} WR "
                    f"over {worst_n} trades"
                ),
                confidence=min(0.8, 0.5 + worst_n / 40),
                evidence_count=worst_n,
                actionable_suggestion=(
                    f"Consider pausing trading or raising confidence floor "
                    f"to 75%+ during {worst_bucket} ({lo}:00-{hi}:00 UTC)."
                ),
                timestamp=now,
            ))

        return insights

    def _analyze_regime_bias(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Compare win rates across regime types."""
        insights = []
        by_regime: Dict[str, List[Dict]] = defaultdict(list)

        for t in trades:
            regime = t.get("regime", "") or "unknown"
            by_regime[regime].append(t)

        overall_wr = _win_rate(trades)
        total_trades = len(trades)

        for regime, regime_trades in by_regime.items():
            if regime == "unknown" or len(regime_trades) < 3:
                continue

            wr = _win_rate(regime_trades)
            n = len(regime_trades)
            trade_share = n / total_trades

            # Overtrading in a losing regime
            if wr < 0.40 and trade_share > 0.25 and n >= 5:
                insights.append(MetaInsight(
                    category="bias",
                    description=(
                        f"Overtrading in losing regime: '{regime}' has "
                        f"{wr:.0%} WR but accounts for {trade_share:.0%} "
                        f"of trades ({n}/{total_trades})"
                    ),
                    confidence=min(0.85, 0.5 + n / 40),
                    evidence_count=n,
                    actionable_suggestion=(
                        f"Reduce trade frequency in '{regime}' regime. "
                        f"Consider auto-veto or raised confidence floor "
                        f"when regime='{regime}'."
                    ),
                    timestamp=now,
                ))

            # Strong regime edge
            if wr >= 0.65 and n >= 5:
                insights.append(MetaInsight(
                    category="edge",
                    description=(
                        f"Strong edge in '{regime}' regime: {wr:.0%} WR "
                        f"over {n} trades (overall: {overall_wr:.0%})"
                    ),
                    confidence=min(0.85, 0.5 + n / 40),
                    evidence_count=n,
                    actionable_suggestion=(
                        f"Size UP in '{regime}' regime. Lower confidence "
                        f"floor by 3-5% when regime='{regime}'."
                    ),
                    timestamp=now,
                ))

            # Weak regime
            if wr < 0.35 and n >= 5:
                insights.append(MetaInsight(
                    category="weakness",
                    description=(
                        f"Weak performance in '{regime}' regime: {wr:.0%} "
                        f"WR over {n} trades"
                    ),
                    confidence=min(0.80, 0.5 + n / 40),
                    evidence_count=n,
                    actionable_suggestion=(
                        f"Avoid or reduce trading in '{regime}' regime. "
                        f"Set LLM to auto-flat when regime='{regime}'."
                    ),
                    timestamp=now,
                ))

        return insights

    def _analyze_confidence_calibration(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Check if confidence levels are well-calibrated.

        Bins trades into 60-70, 70-80, 80-90, 90+ confidence buckets
        and compares stated confidence with actual win rates.
        """
        insights = []

        bins = {
            "60-70": (60, 70),
            "70-80": (70, 80),
            "80-90": (80, 90),
            "90+":   (90, 101),
        }

        bin_data: Dict[str, List[Dict]] = defaultdict(list)
        for t in trades:
            conf = _parse_float(t.get("confidence", 0))
            if conf <= 0:
                continue
            for label, (lo, hi) in bins.items():
                if lo <= conf < hi:
                    bin_data[label].append(t)
                    break

        calibration_issues = []
        for label, (lo, hi) in bins.items():
            bucket_trades = bin_data.get(label, [])
            if len(bucket_trades) < 3:
                continue

            actual_wr = _win_rate(bucket_trades)
            expected_mid = (lo + min(hi, 100)) / 200  # midpoint as probability
            n = len(bucket_trades)

            # Track for cross-bin analysis
            calibration_issues.append((label, expected_mid, actual_wr, n))

            # Overconfident: stated high confidence but low WR
            if lo >= 80 and actual_wr < 0.50 and n >= 3:
                insights.append(MetaInsight(
                    category="bias",
                    description=(
                        f"Overconfidence detected: {label}% confidence "
                        f"signals have only {actual_wr:.0%} actual WR "
                        f"over {n} trades"
                    ),
                    confidence=min(0.85, 0.5 + n / 30),
                    evidence_count=n,
                    actionable_suggestion=(
                        f"Discount high-confidence signals. Consider "
                        f"capping effective confidence at 85% or adding "
                        f"a confidence deflation factor of 0.9."
                    ),
                    timestamp=now,
                ))

            # Underconfident: stated low confidence but high WR
            if hi <= 80 and actual_wr >= 0.65 and n >= 5:
                insights.append(MetaInsight(
                    category="edge",
                    description=(
                        f"Hidden edge at lower confidence: {label}% "
                        f"confidence signals actually win {actual_wr:.0%} "
                        f"of the time over {n} trades"
                    ),
                    confidence=min(0.75, 0.4 + n / 40),
                    evidence_count=n,
                    actionable_suggestion=(
                        f"Consider lowering confidence floor — these "
                        f"'moderate confidence' trades are actually winners. "
                        f"Reduce floor by 5% to capture more of them."
                    ),
                    timestamp=now,
                ))

        # Check monotonicity: does higher confidence actually predict better outcomes?
        if len(calibration_issues) >= 3:
            confs = [c[1] for c in calibration_issues]
            wrs = [c[2] for c in calibration_issues]
            r = _pearson_r(confs, wrs)

            if r < 0.0:
                total_n = sum(c[3] for c in calibration_issues)
                insights.append(MetaInsight(
                    category="bias",
                    description=(
                        f"Confidence is ANTI-correlated with outcomes "
                        f"(r={r:.2f}): higher confidence signals actually "
                        f"perform worse"
                    ),
                    confidence=min(0.80, 0.5 + total_n / 60),
                    evidence_count=total_n,
                    actionable_suggestion=(
                        "Confidence scoring is broken — investigate why "
                        "high-confidence signals underperform. May need to "
                        "recalibrate or invert confidence weighting."
                    ),
                    timestamp=now,
                ))

        return insights

    def _analyze_strategy_clustering(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Check if we rely too heavily on one strategy."""
        insights = []
        by_strategy: Dict[str, List[Dict]] = defaultdict(list)

        for t in trades:
            strat = t.get("strategy", "") or "unknown"
            by_strategy[strat].append(t)

        total_trades = len(trades)
        if total_trades < 5 or len(by_strategy) < 2:
            return insights

        # Check concentration
        counts = sorted(
            [(s, len(ts)) for s, ts in by_strategy.items()],
            key=lambda x: x[1], reverse=True,
        )

        top_strat, top_count = counts[0]
        top_share = top_count / total_trades

        if top_share > 0.60 and top_count >= 5:
            top_wr = _win_rate(by_strategy[top_strat])
            insights.append(MetaInsight(
                category="bias",
                description=(
                    f"Strategy concentration: '{top_strat}' accounts for "
                    f"{top_share:.0%} of all trades ({top_count}/{total_trades}). "
                    f"WR: {top_wr:.0%}"
                ),
                confidence=min(0.80, 0.5 + top_count / 40),
                evidence_count=top_count,
                actionable_suggestion=(
                    f"Diversify: over-reliance on '{top_strat}' creates "
                    f"fragility. Consider reducing its ensemble weight or "
                    f"boosting underrepresented strategies."
                ),
                timestamp=now,
            ))

        # Find underperforming strategies
        for strat, strat_trades in by_strategy.items():
            if strat == "unknown" or len(strat_trades) < 5:
                continue
            wr = _win_rate(strat_trades)
            if wr < 0.35:
                insights.append(MetaInsight(
                    category="weakness",
                    description=(
                        f"Strategy '{strat}' underperforming: {wr:.0%} WR "
                        f"over {len(strat_trades)} trades"
                    ),
                    confidence=min(0.80, 0.5 + len(strat_trades) / 40),
                    evidence_count=len(strat_trades),
                    actionable_suggestion=(
                        f"Reduce weight for '{strat}' in ensemble. "
                        f"Consider disabling if <30% WR persists over "
                        f"20+ trades."
                    ),
                    timestamp=now,
                ))

        return insights

    def _analyze_sizing_patterns(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Compare outcomes for trades above/below median position size."""
        insights = []

        # Use leverage as a proxy for sizing (or a dedicated "size" field)
        sizes = []
        for t in trades:
            size = _parse_float(t.get("leverage", 0))
            if size <= 0:
                size = _parse_float(t.get("size", 0))
            if size > 0:
                sizes.append(size)

        if len(sizes) < 6:
            return insights

        med = _median(sizes)
        if med <= 0:
            return insights

        large_trades = [
            t for t in trades
            if _parse_float(t.get("leverage", 0) or t.get("size", 0)) > med
        ]
        small_trades = [
            t for t in trades
            if 0 < _parse_float(t.get("leverage", 0) or t.get("size", 0)) <= med
        ]

        if len(large_trades) < 3 or len(small_trades) < 3:
            return insights

        large_wr = _win_rate(large_trades)
        small_wr = _win_rate(small_trades)
        large_avg = _avg_pnl(large_trades)
        small_avg = _avg_pnl(small_trades)

        # Large positions doing worse
        if large_wr < small_wr - 0.10 and len(large_trades) >= 5:
            insights.append(MetaInsight(
                category="bias",
                description=(
                    f"Size bias detected: larger positions (>{med:.1f}x) "
                    f"have {large_wr:.0%} WR vs {small_wr:.0%} for smaller "
                    f"positions. Avg PnL: ${large_avg:+.2f} vs ${small_avg:+.2f}"
                ),
                confidence=min(
                    0.80,
                    0.4 + (len(large_trades) + len(small_trades)) / 60,
                ),
                evidence_count=len(large_trades) + len(small_trades),
                actionable_suggestion=(
                    "Reduce position sizes — larger positions are losing "
                    "more often. Consider capping leverage or adding a "
                    "size penalty to the confidence calculation."
                ),
                timestamp=now,
            ))

        # Large positions doing better (size edge)
        if large_wr > small_wr + 0.15 and len(large_trades) >= 5:
            insights.append(MetaInsight(
                category="edge",
                description=(
                    f"Size edge: larger positions (>{med:.1f}x) have "
                    f"{large_wr:.0%} WR vs {small_wr:.0%} for smaller. "
                    f"Higher conviction trades are more profitable."
                ),
                confidence=min(
                    0.75,
                    0.4 + (len(large_trades) + len(small_trades)) / 60,
                ),
                evidence_count=len(large_trades) + len(small_trades),
                actionable_suggestion=(
                    "High-conviction sizing is working. Consider increasing "
                    "sizes on high-confidence setups and further reducing "
                    "sizes on low-confidence ones."
                ),
                timestamp=now,
            ))

        return insights

    def _analyze_veto_patterns(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Check if vetoed trades (if available) correlate with outcomes."""
        insights = []

        # Look for veto-related fields
        vetoed_trades = [
            t for t in trades if t.get("vetoed") or t.get("llm_vetoed")
        ]
        non_vetoed_trades = [
            t for t in trades
            if not t.get("vetoed") and not t.get("llm_vetoed")
        ]

        # Also check for LLM agreement field
        agreed_trades = [
            t for t in trades if t.get("llm_agreed") is True
        ]
        disagreed_trades = [
            t for t in trades if t.get("llm_agreed") is False
        ]

        if len(agreed_trades) >= 3 and len(disagreed_trades) >= 3:
            agreed_wr = _win_rate(agreed_trades)
            disagreed_wr = _win_rate(disagreed_trades)

            if agreed_wr > disagreed_wr + 0.15:
                insights.append(MetaInsight(
                    category="pattern",
                    description=(
                        f"LLM agreement predicts outcomes: trades where "
                        f"LLM agreed have {agreed_wr:.0%} WR vs "
                        f"{disagreed_wr:.0%} when LLM disagreed"
                    ),
                    confidence=min(
                        0.80,
                        0.4 + (len(agreed_trades) + len(disagreed_trades)) / 40,
                    ),
                    evidence_count=len(agreed_trades) + len(disagreed_trades),
                    actionable_suggestion=(
                        "LLM agreement is a strong signal. Consider adding "
                        "a confidence boost (+5%) when LLM agrees with the "
                        "ensemble, and a penalty (-10%) when it disagrees."
                    ),
                    timestamp=now,
                ))

            if disagreed_wr > agreed_wr + 0.15:
                insights.append(MetaInsight(
                    category="bias",
                    description=(
                        f"LLM agreement is ANTI-predictive: trades where "
                        f"LLM disagreed have {disagreed_wr:.0%} WR vs "
                        f"{agreed_wr:.0%} when it agreed"
                    ),
                    confidence=min(
                        0.75,
                        0.4 + (len(agreed_trades) + len(disagreed_trades)) / 40,
                    ),
                    evidence_count=len(agreed_trades) + len(disagreed_trades),
                    actionable_suggestion=(
                        "LLM veto logic may be inverted or miscalibrated. "
                        "Review what the LLM is basing vetoes on. Consider "
                        "inverting the LLM signal or reducing its weight."
                    ),
                    timestamp=now,
                ))

        return insights

    def _analyze_side_bias(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Check for long/short bias."""
        insights = []
        by_side: Dict[str, List[Dict]] = defaultdict(list)

        for t in trades:
            side = (t.get("side", "") or "").upper()
            if side in ("LONG", "BUY"):
                by_side["LONG"].append(t)
            elif side in ("SHORT", "SELL"):
                by_side["SHORT"].append(t)

        long_trades = by_side.get("LONG", [])
        short_trades = by_side.get("SHORT", [])

        if len(long_trades) < 3 or len(short_trades) < 3:
            return insights

        long_wr = _win_rate(long_trades)
        short_wr = _win_rate(short_trades)
        total = len(long_trades) + len(short_trades)
        long_share = len(long_trades) / total

        # Large side imbalance with performance difference
        if abs(long_share - 0.5) > 0.20 and abs(long_wr - short_wr) > 0.10:
            dominant = "LONG" if long_share > 0.5 else "SHORT"
            dom_wr = long_wr if dominant == "LONG" else short_wr
            other_wr = short_wr if dominant == "LONG" else long_wr
            dom_share = long_share if dominant == "LONG" else (1 - long_share)

            if dom_wr < other_wr:
                insights.append(MetaInsight(
                    category="bias",
                    description=(
                        f"Side bias: {dom_share:.0%} of trades are {dominant} "
                        f"but {dominant} WR is {dom_wr:.0%} vs "
                        f"{other_wr:.0%} for the other side"
                    ),
                    confidence=min(0.75, 0.4 + total / 40),
                    evidence_count=total,
                    actionable_suggestion=(
                        f"Reduce {dominant} bias — we're taking too many "
                        f"{dominant} trades that underperform. Consider "
                        f"adding a side-balance check to the ensemble."
                    ),
                    timestamp=now,
                ))

        return insights

    def _analyze_streak_patterns(
        self, trades: List[Dict], now: float
    ) -> List[MetaInsight]:
        """Analyze consecutive win/loss streaks for pattern insights."""
        insights = []

        # Sort by timestamp
        sorted_trades = sorted(trades, key=lambda t: _parse_trade_ts(t))
        if len(sorted_trades) < 10:
            return insights

        # Build outcome sequence
        outcomes = [
            1 if _parse_float(t.get("pnl", 0)) > 0 else 0
            for t in sorted_trades
        ]

        # Find max loss streak
        max_loss_streak = 0
        current_streak = 0
        for o in outcomes:
            if o == 0:
                current_streak += 1
                max_loss_streak = max(max_loss_streak, current_streak)
            else:
                current_streak = 0

        # Check if we trade worse after consecutive losses
        # (emotional tilt detection)
        if max_loss_streak >= 3:
            after_loss_streak_trades = []
            streak_count = 0
            for i, o in enumerate(outcomes):
                if o == 0:
                    streak_count += 1
                else:
                    streak_count = 0
                # Trade immediately after a 3+ loss streak
                if streak_count == 0 and i > 0 and i < len(outcomes):
                    # Check if the previous run was a 3+ streak
                    prev_streak = 0
                    for j in range(i - 1, -1, -1):
                        if outcomes[j] == 0:
                            prev_streak += 1
                        else:
                            break
                    if prev_streak >= 3:
                        after_loss_streak_trades.append(sorted_trades[i])

            if len(after_loss_streak_trades) >= 3:
                post_streak_wr = _win_rate(after_loss_streak_trades)
                overall_wr = _win_rate(trades)

                if post_streak_wr < overall_wr - 0.15:
                    insights.append(MetaInsight(
                        category="bias",
                        description=(
                            f"Possible tilt effect: trades after 3+ loss "
                            f"streaks have {post_streak_wr:.0%} WR vs "
                            f"{overall_wr:.0%} overall "
                            f"(max streak: {max_loss_streak})"
                        ),
                        confidence=min(
                            0.70,
                            0.4 + len(after_loss_streak_trades) / 20,
                        ),
                        evidence_count=len(after_loss_streak_trades),
                        actionable_suggestion=(
                            "Consider adding a cooldown period after 3+ "
                            "consecutive losses. Raise confidence floor by "
                            "10% during loss streaks to filter marginal trades."
                        ),
                        timestamp=now,
                    ))

        return insights

    # ------------------------------------------------------------------
    # Strategy idea generation
    # ------------------------------------------------------------------

    def generate_strategy_ideas(
        self,
        insights: List[MetaInsight],
        market_state: Dict,
    ) -> List[StrategyIdea]:
        """Generate new strategy ideas from meta-insights.

        Maps patterns to concrete, testable strategy modifications:
        - Time-of-day edges -> Time-weighted confidence adjustments
        - Regime edges -> Regime-specific parameter overrides
        - Confidence calibration issues -> Calibration curve adjustments
        - Strategy clustering -> Weight rebalancing proposals
        - Sizing patterns -> Dynamic sizing rules
        - Consensus patterns -> Consensus-only modes during drawdown

        Args:
            insights: List of MetaInsight objects from analyze_decision_patterns.
            market_state: Current market state dict (regime, volatility, etc.).

        Returns:
            List of newly generated StrategyIdea objects.
        """
        with self._lock:
            self._ensure_loaded()

        if not insights:
            return []

        ideas: List[StrategyIdea] = []
        now = time.time()
        current_regime = market_state.get("regime", "unknown")

        for insight in insights:
            generated = self._insight_to_idea(insight, market_state, now)
            if generated:
                # Deduplicate against existing ideas
                if not self._idea_exists(generated.name):
                    ideas.append(generated)

        # Store new ideas
        with self._lock:
            self._ideas.extend(ideas)
            self._save_ideas()

        if ideas:
            logger.info(
                f"[META] Generated {len(ideas)} new strategy ideas "
                f"from {len(insights)} insights"
            )

        return ideas

    @staticmethod
    def _extract_quoted(text: str) -> List[str]:
        """Extract all single-quoted values from a text string.

        Example: "edge in 'trending' regime: 68% WR" -> ["trending"]
        """
        parts = text.split("'")
        # Odd-indexed parts are inside quotes: a'b'c'd' -> [a, b, c, d]
        return [parts[i] for i in range(1, len(parts), 2) if parts[i].strip()]

    def _insight_to_idea(
        self,
        insight: MetaInsight,
        market_state: Dict,
        now: float,
    ) -> Optional[StrategyIdea]:
        """Convert a single insight into a strategy idea, if applicable."""

        desc = insight.description.lower()
        # Extract all single-quoted values from the original description
        # (use the original case for proper regime names)
        quoted_values = self._extract_quoted(insight.description)

        # --- Time-of-day pattern -> time-weighted confidence ---
        if "time-of-day" in desc or "trading hour" in desc or "time bucket" in desc:
            # Extract the best/worst bucket from description
            best_bucket = None
            worst_bucket = None
            for bucket_name in _TIME_BUCKETS:
                if f"'{bucket_name}'" in desc:
                    if best_bucket is None:
                        best_bucket = bucket_name
                    else:
                        worst_bucket = bucket_name

            if best_bucket:
                lo, hi = _TIME_BUCKETS[best_bucket]
                return StrategyIdea(
                    id=f"idea_{uuid.uuid4().hex[:8]}",
                    name=f"Time-weighted confidence: boost {best_bucket}",
                    description=(
                        f"Apply a confidence multiplier of 1.08 for trades "
                        f"during {best_bucket} ({lo}:00-{hi}:00 UTC) based "
                        f"on observed time-of-day edge."
                    ),
                    trigger_condition=(
                        f"When current UTC hour is between {lo} and {hi}"
                    ),
                    parameters={
                        "confidence_multiplier": 1.08,
                        "time_bucket": best_bucket,
                        "utc_hours": [lo, hi],
                    },
                    expected_edge=(
                        f"~5-10% WR improvement during {best_bucket} hours"
                    ),
                    source_pattern=insight.description,
                    status="proposed",
                    created_at=now,
                    updated_at=now,
                )

        # --- Regime edge -> regime-specific filter ---
        if "regime" in desc and insight.category == "edge":
            # Extract regime name from quoted value in description
            regime_name = quoted_values[0] if quoted_values else None

            if regime_name:
                return StrategyIdea(
                    id=f"idea_{uuid.uuid4().hex[:8]}",
                    name=f"Regime-aware sizing: boost in {regime_name}",
                    description=(
                        f"Increase position size by 20% and lower "
                        f"confidence floor by 5% when regime is "
                        f"'{regime_name}', based on observed edge."
                    ),
                    trigger_condition=(
                        f"When market regime is '{regime_name}'"
                    ),
                    parameters={
                        "size_multiplier": 1.2,
                        "confidence_floor_adj": -5,
                        "target_regime": regime_name,
                    },
                    expected_edge=(
                        f"Capture more trades in high-WR regime "
                        f"'{regime_name}'"
                    ),
                    source_pattern=insight.description,
                    status="proposed",
                    created_at=now,
                    updated_at=now,
                )

        # --- Regime weakness -> avoidance filter ---
        if "regime" in desc and insight.category in ("weakness", "bias"):
            # Extract regime name from quoted value in description
            regime_name = quoted_values[0] if quoted_values else None

            if regime_name:
                return StrategyIdea(
                    id=f"idea_{uuid.uuid4().hex[:8]}",
                    name=f"Regime avoidance: reduce in {regime_name}",
                    description=(
                        f"Raise confidence floor by 10% and reduce "
                        f"max position count when regime is "
                        f"'{regime_name}' to avoid losses."
                    ),
                    trigger_condition=(
                        f"When market regime is '{regime_name}'"
                    ),
                    parameters={
                        "confidence_floor_adj": +10,
                        "max_positions_override": 1,
                        "target_regime": regime_name,
                    },
                    expected_edge=(
                        f"Avoid ~30-50% of losing trades in "
                        f"'{regime_name}' regime"
                    ),
                    source_pattern=insight.description,
                    status="proposed",
                    created_at=now,
                    updated_at=now,
                )

        # --- Overconfidence -> calibration adjustment ---
        if "overconfidence" in desc or "anti-correlated" in desc:
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Confidence deflation filter",
                description=(
                    "Apply a 0.90 multiplier to all confidence scores "
                    "above 80% to correct for systematic overconfidence."
                ),
                trigger_condition=(
                    "When signal confidence is above 80%"
                ),
                parameters={
                    "deflation_factor": 0.90,
                    "threshold": 80,
                    "apply_above_only": True,
                },
                expected_edge=(
                    "Reduce false-positive rate for high-confidence signals"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        # --- Hidden edge at low confidence -> floor reduction ---
        if "hidden edge" in desc and "lower confidence" in desc:
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Lower confidence floor to capture hidden edge",
                description=(
                    "Reduce the confidence floor by 5% to capture "
                    "moderate-confidence trades that historically win."
                ),
                trigger_condition="Always active",
                parameters={
                    "confidence_floor_adj": -5,
                    "reason": "hidden_edge_at_moderate_confidence",
                },
                expected_edge=(
                    "Capture profitable trades currently filtered out"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        # --- Strategy concentration -> weight rebalance ---
        if "concentration" in desc and insight.category == "bias":
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Strategy weight rebalancing",
                description=(
                    "Reduce weight of the dominant strategy by 15% and "
                    "redistribute to underrepresented strategies."
                ),
                trigger_condition="Periodic rebalance (every 24h)",
                parameters={
                    "dominant_weight_reduction": 0.15,
                    "redistribute_to_others": True,
                },
                expected_edge=(
                    "Better diversification, reduced fragility to "
                    "single-strategy failure"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        # --- Size bias -> dynamic sizing rule ---
        if "size bias" in desc and "larger positions" in desc:
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Confidence-proportional sizing cap",
                description=(
                    "Cap leverage based on confidence: max 3x below 75% "
                    "confidence, max 5x at 75-85%, full leverage only "
                    "above 85%."
                ),
                trigger_condition="Always active",
                parameters={
                    "tiers": [
                        {"confidence_below": 75, "max_leverage": 3},
                        {"confidence_below": 85, "max_leverage": 5},
                        {"confidence_above": 85, "max_leverage": 10},
                    ]
                },
                expected_edge=(
                    "Reduce outsized losses from high-leverage, low-edge trades"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        # --- Tilt effect -> cooldown circuit breaker ---
        if "tilt" in desc or "loss streak" in desc:
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Post-streak cooldown circuit breaker",
                description=(
                    "After 3 consecutive losses, enforce a 30-minute "
                    "trading cooldown and raise confidence floor by 10% "
                    "for the next 2 hours."
                ),
                trigger_condition=(
                    "When consecutive_losses >= 3"
                ),
                parameters={
                    "cooldown_minutes": 30,
                    "confidence_floor_boost": 10,
                    "boost_duration_hours": 2,
                    "trigger_streak_length": 3,
                },
                expected_edge=(
                    "Prevent tilt-driven trades after loss streaks"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        # --- Side bias -> side balance filter ---
        if "side bias" in desc:
            return StrategyIdea(
                id=f"idea_{uuid.uuid4().hex[:8]}",
                name="Side balance enforcement",
                description=(
                    "Add a side-balance penalty: if >65% of recent trades "
                    "are one side, apply a -5% confidence adjustment to "
                    "additional same-side trades."
                ),
                trigger_condition=(
                    "When recent side imbalance exceeds 65%"
                ),
                parameters={
                    "imbalance_threshold": 0.65,
                    "confidence_penalty": -5,
                    "lookback_trades": 20,
                },
                expected_edge=(
                    "Reduce directional bias that leads to concentrated losses"
                ),
                source_pattern=insight.description,
                status="proposed",
                created_at=now,
                updated_at=now,
            )

        return None

    def _idea_exists(self, name: str) -> bool:
        """Check if an idea with similar name already exists (active only)."""
        name_lower = name.lower().strip()
        for idea in self._ideas:
            if idea.status in ("proposed", "testing"):
                if idea.name.lower().strip() == name_lower:
                    return True
        return False

    # ------------------------------------------------------------------
    # Idea evaluation
    # ------------------------------------------------------------------

    def evaluate_idea(self, idea_id: str, outcomes: List[Dict]) -> Dict:
        """Evaluate a strategy idea against real outcomes.

        Args:
            idea_id: The ID of the idea to evaluate.
            outcomes: List of trade dicts collected while the idea was
                being tested.

        Returns:
            Dict with evaluation results including win_rate, avg_pnl,
            sample_size, and a verdict (validated/rejected/inconclusive).
        """
        with self._lock:
            self._ensure_loaded()

        idea = None
        for i in self._ideas:
            if i.id == idea_id:
                idea = i
                break

        if idea is None:
            return {"error": f"Idea '{idea_id}' not found"}

        if not outcomes:
            return {
                "idea_id": idea_id,
                "verdict": "inconclusive",
                "reason": "No outcome data provided",
            }

        wr = _win_rate(outcomes)
        avg = _avg_pnl(outcomes)
        n = len(outcomes)

        # Determine verdict
        if n < 5:
            verdict = "inconclusive"
            reason = f"Only {n} trades — need at least 5 for evaluation"
        elif wr >= 0.55 and avg > 0:
            verdict = "validated"
            reason = f"Positive edge: {wr:.0%} WR, ${avg:+.2f} avg PnL over {n} trades"
        elif wr < 0.45 or avg < 0:
            verdict = "rejected"
            reason = f"Negative results: {wr:.0%} WR, ${avg:+.2f} avg PnL over {n} trades"
        else:
            verdict = "inconclusive"
            reason = f"Marginal results: {wr:.0%} WR, ${avg:+.2f} avg PnL — needs more data"

        result = {
            "idea_id": idea_id,
            "win_rate": round(wr, 4),
            "avg_pnl": round(avg, 4),
            "sample_size": n,
            "verdict": verdict,
            "reason": reason,
            "evaluated_at": time.time(),
        }

        # Update idea status and test_results
        with self._lock:
            idea.test_results = result
            idea.updated_at = time.time()
            if verdict == "validated":
                idea.status = "validated"
            elif verdict == "rejected":
                idea.status = "rejected"
            # 'inconclusive' keeps status as 'testing'
            self._save_ideas()

        logger.info(
            f"[META] Evaluated idea '{idea.name}': {verdict} — {reason}"
        )
        return result

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_ideas(self) -> List[StrategyIdea]:
        """Get ideas currently proposed or being tested."""
        with self._lock:
            self._ensure_loaded()
            return [
                i for i in self._ideas
                if i.status in ("proposed", "testing")
            ]

    def get_recent_insights(self, limit: int = 20) -> List[MetaInsight]:
        """Get the most recent insights."""
        with self._lock:
            self._ensure_loaded()
            return sorted(
                self._insights,
                key=lambda i: i.timestamp,
                reverse=True,
            )[:limit]

    def get_ideas_by_status(self, status: str) -> List[StrategyIdea]:
        """Get ideas filtered by status."""
        with self._lock:
            self._ensure_loaded()
            return [i for i in self._ideas if i.status == status]

    def start_testing_idea(self, idea_id: str) -> bool:
        """Move an idea from proposed to testing status."""
        with self._lock:
            self._ensure_loaded()
            for idea in self._ideas:
                if idea.id == idea_id and idea.status == "proposed":
                    idea.status = "testing"
                    idea.updated_at = time.time()
                    self._save_ideas()
                    logger.info(f"[META] Now testing idea: {idea.name}")
                    return True
        return False

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_meta_report(self) -> str:
        """Generate a full meta-learning report as formatted text."""
        with self._lock:
            self._ensure_loaded()

        lines = []
        sep = "=" * 70

        lines.append(sep)
        lines.append("  META-LEARNING ENGINE REPORT")
        lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"  Total insights: {len(self._insights)} | "
                      f"Total ideas: {len(self._ideas)}")
        lines.append(sep)

        # --- Recent Insights ---
        recent_insights = self.get_recent_insights(15)
        if recent_insights:
            lines.append("")
            lines.append("  RECENT INSIGHTS")
            lines.append("  " + "-" * 60)

            by_category: Dict[str, List[MetaInsight]] = defaultdict(list)
            for ins in recent_insights:
                by_category[ins.category].append(ins)

            category_labels = {
                "edge": "[EDGE]",
                "pattern": "[PTRN]",
                "bias": "[BIAS]",
                "weakness": "[WEAK]",
            }

            for cat in ("edge", "pattern", "bias", "weakness"):
                cat_insights = by_category.get(cat, [])
                if not cat_insights:
                    continue
                for ins in cat_insights:
                    label = category_labels.get(cat, f"[{cat.upper()[:4]}]")
                    lines.append(
                        f"  {label} {ins.description[:100]}"
                    )
                    lines.append(
                        f"         Conf: {ins.confidence:.0%} | "
                        f"Evidence: {ins.evidence_count} trades"
                    )
                    lines.append(
                        f"         Action: {ins.actionable_suggestion[:100]}"
                    )
                    lines.append("")

        # --- Active Strategy Ideas ---
        active_ideas = self.get_active_ideas()
        if active_ideas:
            lines.append("  ACTIVE STRATEGY IDEAS")
            lines.append("  " + "-" * 60)

            for idea in active_ideas[:10]:
                status_tag = (
                    "[PROPOSED]" if idea.status == "proposed" else "[TESTING]"
                )
                lines.append(f"  {status_tag} {idea.name}")
                lines.append(f"    {idea.description[:100]}")
                lines.append(f"    Trigger: {idea.trigger_condition[:80]}")
                lines.append(f"    Expected: {idea.expected_edge[:80]}")
                if idea.test_results:
                    tr = idea.test_results
                    lines.append(
                        f"    Results: WR={tr.get('win_rate', 0):.0%}, "
                        f"Avg=${tr.get('avg_pnl', 0):+.2f}, "
                        f"N={tr.get('sample_size', 0)}"
                    )
                lines.append("")

        # --- Validated/Rejected Ideas ---
        validated = self.get_ideas_by_status("validated")
        rejected = self.get_ideas_by_status("rejected")

        if validated:
            lines.append("  VALIDATED IDEAS (proven edge)")
            lines.append("  " + "-" * 60)
            for idea in validated[:5]:
                lines.append(f"  [OK] {idea.name}")
                tr = idea.test_results
                if tr:
                    lines.append(
                        f"       WR={tr.get('win_rate', 0):.0%}, "
                        f"N={tr.get('sample_size', 0)} — {tr.get('reason', '')}"
                    )
            lines.append("")

        if rejected:
            lines.append("  REJECTED IDEAS (disproven)")
            lines.append("  " + "-" * 60)
            for idea in rejected[:5]:
                lines.append(f"  [X] {idea.name}")
                tr = idea.test_results
                if tr:
                    lines.append(
                        f"      WR={tr.get('win_rate', 0):.0%}, "
                        f"N={tr.get('sample_size', 0)} — {tr.get('reason', '')}"
                    )
            lines.append("")

        # --- Summary statistics ---
        idea_stats = defaultdict(int)
        for idea in self._ideas:
            idea_stats[idea.status] += 1

        insight_stats = defaultdict(int)
        for ins in self._insights:
            insight_stats[ins.category] += 1

        lines.append("  SUMMARY")
        lines.append("  " + "-" * 60)
        lines.append(
            f"  Ideas: {idea_stats.get('proposed', 0)} proposed, "
            f"{idea_stats.get('testing', 0)} testing, "
            f"{idea_stats.get('validated', 0)} validated, "
            f"{idea_stats.get('rejected', 0)} rejected"
        )
        lines.append(
            f"  Insights: {insight_stats.get('edge', 0)} edges, "
            f"{insight_stats.get('pattern', 0)} patterns, "
            f"{insight_stats.get('bias', 0)} biases, "
            f"{insight_stats.get('weakness', 0)} weaknesses"
        )
        lines.append(
            f"  Ticks: {self._tick_state.get('total_ticks', 0)} | "
            f"Last: {self._format_ago(self._tick_state.get('last_tick_ts', 0))}"
        )
        lines.append(sep)

        return "\n".join(lines)

    @staticmethod
    def _format_ago(ts: float) -> str:
        """Format a timestamp as a relative 'ago' string."""
        if ts <= 0:
            return "never"
        elapsed = time.time() - ts
        if elapsed < 60:
            return f"{elapsed:.0f}s ago"
        if elapsed < 3600:
            return f"{elapsed / 60:.0f}m ago"
        if elapsed < 86400:
            return f"{elapsed / 3600:.1f}h ago"
        return f"{elapsed / 86400:.1f}d ago"

    # ------------------------------------------------------------------
    # Periodic tick
    # ------------------------------------------------------------------

    def tick(
        self,
        recent_trades: List[Dict] = None,
        market_state: Dict = None,
    ):
        """Periodic tick: analyze patterns, generate ideas, evaluate active.

        Designed to be called periodically (e.g., every 1-4 hours) by the
        bot's main loop. It:
        1. Analyzes recent trades for decision patterns
        2. Generates strategy ideas from discovered insights
        3. Evaluates any active ideas against recent outcomes

        Args:
            recent_trades: List of recent trade dicts. If None, no analysis
                is performed.
            market_state: Current market state dict. If None, uses an
                empty dict for idea generation.
        """
        if recent_trades is None:
            recent_trades = []
        if market_state is None:
            market_state = {}

        logger.info(
            f"[META] Tick: {len(recent_trades)} trades, "
            f"market_state keys: {list(market_state.keys())}"
        )

        # 1. Analyze decision patterns
        insights = []
        if recent_trades:
            insights = self.analyze_decision_patterns(
                recent_trades, lookback_days=14
            )

        # 2. Generate strategy ideas from new insights
        if insights:
            self.generate_strategy_ideas(insights, market_state)

        # 3. Evaluate active ideas (testing status) against recent outcomes
        active = self.get_active_ideas()
        for idea in active:
            if idea.status == "testing":
                # Use all recent trades as evaluation data
                # (In practice, you'd filter to trades taken while the
                #  idea's conditions were active)
                if len(recent_trades) >= 5:
                    self.evaluate_idea(idea.id, recent_trades)

        # Update tick state
        with self._lock:
            self._tick_state["last_tick_ts"] = time.time()
            self._tick_state["total_ticks"] = (
                self._tick_state.get("total_ticks", 0) + 1
            )
            self._tick_state["last_insights_count"] = len(insights)
            self._tick_state["last_active_ideas"] = len(active)
            self._save_tick_state()

        logger.info(
            f"[META] Tick complete: {len(insights)} insights, "
            f"{len(active)} active ideas evaluated"
        )

    # ------------------------------------------------------------------
    # Stats for external consumers
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics for monitoring/dashboards."""
        with self._lock:
            self._ensure_loaded()

        idea_status = defaultdict(int)
        for idea in self._ideas:
            idea_status[idea.status] += 1

        insight_cats = defaultdict(int)
        for ins in self._insights:
            insight_cats[ins.category] += 1

        return {
            "total_insights": len(self._insights),
            "total_ideas": len(self._ideas),
            "ideas_by_status": dict(idea_status),
            "insights_by_category": dict(insight_cats),
            "total_ticks": self._tick_state.get("total_ticks", 0),
            "last_tick_ts": self._tick_state.get("last_tick_ts", 0),
            "last_insights_count": self._tick_state.get(
                "last_insights_count", 0
            ),
        }

    def format_for_llm_prompt(self) -> str:
        """Format current meta-learning state for LLM prompt injection."""
        with self._lock:
            self._ensure_loaded()

        lines = []

        # Recent high-confidence insights
        recent = [
            i for i in self._insights
            if i.confidence >= 0.6
        ]
        recent = sorted(recent, key=lambda i: i.timestamp, reverse=True)[:5]

        if recent:
            lines.append("META-LEARNING INSIGHTS:")
            for ins in recent:
                cat_tag = ins.category.upper()[:4]
                lines.append(
                    f"  [{cat_tag}] {ins.description[:120]} "
                    f"(conf={ins.confidence:.0%})"
                )

        # Active ideas
        active = self.get_active_ideas()[:3]
        if active:
            lines.append("ACTIVE STRATEGY IDEAS BEING TESTED:")
            for idea in active:
                lines.append(
                    f"  [{idea.status.upper()}] {idea.name}: "
                    f"{idea.trigger_condition[:80]}"
                )

        return "\n".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[MetaLearningEngine] = None
_engine_lock = threading.Lock()


def get_meta_engine() -> MetaLearningEngine:
    """Singleton accessor for MetaLearningEngine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = MetaLearningEngine()
    return _engine
