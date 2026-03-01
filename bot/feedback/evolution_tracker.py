"""
Strategy Evolution Tracker — the "TRUE STUDENT" module.

This module answers three questions:
  1. WHERE is my edge coming from? (edge attribution)
  2. HOW is my edge changing over time? (growth trajectory)
  3. WHAT should I do next to improve? (actionable lessons)

It reads from existing data sources (decisions.jsonl, trades.csv, signal_quality,
memory_store, strategy_weights) and produces evolution reports that show:
  - Win rate trajectory (daily/weekly rolling windows)
  - Edge attribution by dimension (regime, strategy, trigger, time-of-day, symbol)
  - LLM ROI analysis (did the LLM add value vs baseline ensemble?)
  - Lesson extraction (what patterns are working/failing)
  - Throttle optimization (which triggers produce the highest-ROI calls)
  - Growth recommendations (specific, actionable next steps)

Usage:
    from feedback.evolution_tracker import EvolutionTracker
    tracker = EvolutionTracker("data")
    report = tracker.generate_report()
    print(tracker.format_report(report))
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.feedback.evolution")


# ── Report data structures ───────────────────────────────────────

@dataclass
class WinRateWindow:
    """Win rate over a specific time window."""
    window_label: str       # "24h", "7d", "30d", "all"
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades else 0.0

    @property
    def edge_score(self) -> float:
        """Composite edge: win_rate * avg_pnl (positive = real edge)."""
        if not self.total_trades:
            return 0.0
        return self.win_rate * self.avg_pnl


@dataclass
class DimensionEdge:
    """Edge attribution for one dimension value (e.g., regime=trend)."""
    key: str
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades * 100 if self.trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trades if self.trades else 0.0


@dataclass
class TriggerROI:
    """Return on investment for a specific LLM trigger type."""
    trigger: str
    calls: int = 0
    vetoes: int = 0
    proceeds: int = 0
    veto_saved_pnl: float = 0.0     # estimated PnL saved by vetoes
    proceed_realized_pnl: float = 0.0
    avg_latency_ms: int = 0
    avg_tokens: int = 0

    @property
    def estimated_cost(self) -> float:
        """Estimated API cost for this trigger's calls."""
        # Using Sonnet pricing as upper bound
        avg_input = 2000
        avg_output = 350
        per_call = avg_input * 3.0 / 1e6 + avg_output * 15.0 / 1e6
        return self.calls * per_call

    @property
    def roi(self) -> float:
        """ROI = (value generated) / (cost spent)."""
        cost = self.estimated_cost
        if cost <= 0:
            return 0.0
        value = self.veto_saved_pnl + self.proceed_realized_pnl
        return value / cost


@dataclass
class Lesson:
    """An actionable lesson extracted from performance data."""
    category: str           # "edge", "leak", "opportunity", "risk"
    confidence: float       # 0-1, how confident we are in this lesson
    message: str            # human-readable lesson
    evidence: str           # data backing it up
    action: str             # specific recommendation


@dataclass
class ThrottleRecommendation:
    """Recommended throttle settings based on trigger ROI analysis."""
    current_hourly: int
    current_daily: int
    recommended_hourly: int
    recommended_daily: int
    recommended_model: str
    estimated_monthly_cost: float
    reasoning: str


@dataclass
class EvolutionReport:
    """Complete evolution report — the daily "student journal"."""
    generated_at: str
    # Win rate trajectory
    win_rate_trajectory: List[WinRateWindow] = field(default_factory=list)
    # Edge attribution by dimension
    edge_by_regime: List[DimensionEdge] = field(default_factory=list)
    edge_by_strategy: List[DimensionEdge] = field(default_factory=list)
    edge_by_symbol: List[DimensionEdge] = field(default_factory=list)
    edge_by_hour: List[DimensionEdge] = field(default_factory=list)
    edge_by_side: List[DimensionEdge] = field(default_factory=list)
    # LLM value analysis
    trigger_roi: List[TriggerROI] = field(default_factory=list)
    llm_veto_count: int = 0
    llm_proceed_count: int = 0
    llm_total_calls: int = 0
    llm_estimated_cost: float = 0.0
    # Lessons and recommendations
    lessons: List[Lesson] = field(default_factory=list)
    throttle_rec: Optional[ThrottleRecommendation] = None
    # Raw stats
    total_decisions: int = 0
    total_trades: int = 0
    memory_notes_count: int = 0
    days_of_data: float = 0.0


# ── Main tracker ─────────────────────────────────────────────────

class EvolutionTracker:
    """Reads all data sources and produces evolution reports."""

    def __init__(self, data_dir: str = "data"):
        self._data_dir = data_dir
        self._decisions_path = os.path.join(data_dir, "llm", "decisions.jsonl")
        self._trades_path = os.path.join(data_dir, "trades.csv")
        self._quality_path = os.path.join(data_dir, "feedback", "signal_quality.json")
        self._memory_path = os.path.join(data_dir, "llm", "llm_memory.json")
        self._weights_path = os.path.join("ml_data", "strategy_weights.json")

    # ── Data loading ─────────────────────────────────────────────

    def _load_decisions(self) -> List[Dict[str, Any]]:
        """Load LLM decisions from JSONL audit log."""
        decisions = []
        if not os.path.exists(self._decisions_path):
            return decisions
        try:
            with open(self._decisions_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            decisions.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            logger.warning("Could not read decisions log")
        return decisions

    def _load_trades(self) -> List[Dict[str, str]]:
        """Load closed trades from CSV."""
        trades = []
        if not os.path.exists(self._trades_path):
            return trades
        try:
            import csv
            with open(self._trades_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
        except (OSError, Exception) as e:
            logger.warning(f"Could not read trades CSV: {e}")
        return trades

    def _load_signal_quality(self) -> Dict[str, Any]:
        """Load signal quality tracker state."""
        if not os.path.exists(self._quality_path):
            return {}
        try:
            with open(self._quality_path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_memory(self) -> List[Dict[str, Any]]:
        """Load LLM memory notes."""
        if not os.path.exists(self._memory_path):
            return []
        try:
            with open(self._memory_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("notes", [])
                return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _load_strategy_weights(self) -> Dict[str, Any]:
        """Load strategy weight manager state."""
        if not os.path.exists(self._weights_path):
            return {}
        try:
            with open(self._weights_path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    # ── Analysis engines ─────────────────────────────────────────

    def _compute_win_rate_trajectory(
        self, trades: List[Dict[str, str]]
    ) -> List[WinRateWindow]:
        """Compute win rate across multiple time windows."""
        now = time.time()
        windows = [
            ("24h", 86400),
            ("3d", 259200),
            ("7d", 604800),
            ("14d", 1209600),
            ("30d", 2592000),
            ("all", float("inf")),
        ]

        results = []
        for label, seconds in windows:
            w = WinRateWindow(window_label=label)
            cutoff = now - seconds if seconds != float("inf") else 0

            for trade in trades:
                ts = self._parse_trade_ts(trade)
                if ts < cutoff:
                    continue

                pnl = self._parse_float(trade.get("pnl", "0"))
                w.total_trades += 1
                w.total_pnl += pnl
                if pnl > 0:
                    w.wins += 1
                elif pnl < 0:
                    w.losses += 1

            if w.total_trades > 0:
                w.avg_pnl = w.total_pnl / w.total_trades
            results.append(w)

        return results

    def _compute_edge_by_dimension(
        self, trades: List[Dict[str, str]], dimension: str
    ) -> List[DimensionEdge]:
        """Compute edge attribution for a specific dimension."""
        buckets: Dict[str, DimensionEdge] = {}

        for trade in trades:
            key = trade.get(dimension, "unknown")
            if not key:
                key = "unknown"

            if key not in buckets:
                buckets[key] = DimensionEdge(key=key)

            b = buckets[key]
            pnl = self._parse_float(trade.get("pnl", "0"))
            b.trades += 1
            b.total_pnl += pnl
            if pnl > 0:
                b.wins += 1

        # Sort by total PnL descending (best edges first)
        return sorted(buckets.values(), key=lambda x: x.total_pnl, reverse=True)

    def _compute_edge_by_hour(
        self, trades: List[Dict[str, str]]
    ) -> List[DimensionEdge]:
        """Compute edge by hour-of-day (UTC)."""
        buckets: Dict[str, DimensionEdge] = {}

        for trade in trades:
            ts = self._parse_trade_ts(trade)
            if ts <= 0:
                continue
            hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
            key = f"{hour:02d}:00"

            if key not in buckets:
                buckets[key] = DimensionEdge(key=key)

            b = buckets[key]
            pnl = self._parse_float(trade.get("pnl", "0"))
            b.trades += 1
            b.total_pnl += pnl
            if pnl > 0:
                b.wins += 1

        return sorted(buckets.values(), key=lambda x: x.total_pnl, reverse=True)

    def _compute_trigger_roi(
        self, decisions: List[Dict[str, Any]], trades: List[Dict[str, str]]
    ) -> List[TriggerROI]:
        """Compute ROI per trigger type."""
        triggers: Dict[str, TriggerROI] = {}

        for dec in decisions:
            trigger = dec.get("trigger_reason", "unknown")
            if not trigger:
                trigger = "unknown"

            if trigger not in triggers:
                triggers[trigger] = TriggerROI(trigger=trigger)

            t = triggers[trigger]
            t.calls += 1

            action = dec.get("action", "")
            is_veto = dec.get("is_veto", False)

            if is_veto or action == "flat":
                t.vetoes += 1
            elif action == "proceed":
                t.proceeds += 1

            # Track usage
            usage = dec.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            latency = usage.get("latency_ms", 0)
            # Running average
            if t.calls > 1:
                t.avg_tokens = int(
                    (t.avg_tokens * (t.calls - 1) + tokens) / t.calls
                )
                t.avg_latency_ms = int(
                    (t.avg_latency_ms * (t.calls - 1) + latency) / t.calls
                )
            else:
                t.avg_tokens = tokens
                t.avg_latency_ms = latency

        # Sort by call count descending
        return sorted(triggers.values(), key=lambda x: x.calls, reverse=True)

    def _extract_lessons(
        self,
        trajectory: List[WinRateWindow],
        edge_regime: List[DimensionEdge],
        edge_strategy: List[DimensionEdge],
        edge_symbol: List[DimensionEdge],
        edge_hour: List[DimensionEdge],
        edge_side: List[DimensionEdge],
        trigger_roi: List[TriggerROI],
        decisions: List[Dict[str, Any]],
        memory_notes: List[Dict[str, Any]],
    ) -> List[Lesson]:
        """Extract actionable lessons from all analysis dimensions."""
        lessons = []

        # ── Trajectory lessons ───────────────────────────────────
        recent_24h = next((w for w in trajectory if w.window_label == "24h"), None)
        recent_7d = next((w for w in trajectory if w.window_label == "7d"), None)
        all_time = next((w for w in trajectory if w.window_label == "all"), None)

        if recent_24h and recent_7d and recent_24h.total_trades >= 3:
            if recent_24h.win_rate > recent_7d.win_rate + 10:
                lessons.append(Lesson(
                    category="edge",
                    confidence=0.7,
                    message="Win rate is trending UP (24h above 7d average)",
                    evidence=f"24h: {recent_24h.win_rate:.0f}% vs 7d: {recent_7d.win_rate:.0f}%",
                    action="Current approach is working. Consider slightly increasing position sizes or relaxing confidence floor by 2-3%.",
                ))
            elif recent_24h.win_rate < recent_7d.win_rate - 10:
                lessons.append(Lesson(
                    category="risk",
                    confidence=0.7,
                    message="Win rate is trending DOWN (24h below 7d average)",
                    evidence=f"24h: {recent_24h.win_rate:.0f}% vs 7d: {recent_7d.win_rate:.0f}%",
                    action="Tighten confidence floor +3-5%. Reduce LLM mode aggressiveness. Review what changed in market regime.",
                ))

        if all_time and all_time.total_trades >= 10:
            if all_time.win_rate >= 55:
                lessons.append(Lesson(
                    category="edge",
                    confidence=0.8,
                    message=f"System has a confirmed edge: {all_time.win_rate:.1f}% win rate over {all_time.total_trades} trades",
                    evidence=f"Total PnL: ${all_time.total_pnl:.2f}, Avg: ${all_time.avg_pnl:.2f}/trade",
                    action="Focus on increasing trade frequency in high-edge conditions rather than improving win rate.",
                ))
            elif all_time.win_rate < 45:
                lessons.append(Lesson(
                    category="leak",
                    confidence=0.8,
                    message=f"System is net-negative: {all_time.win_rate:.1f}% win rate",
                    evidence=f"Total PnL: ${all_time.total_pnl:.2f} over {all_time.total_trades} trades",
                    action="Raise confidence floor to 70+. Switch LLM to VETO_ONLY mode. Focus on eliminating losing dimensions before scaling.",
                ))

        # ── Regime edge lessons ──────────────────────────────────
        for edge in edge_regime:
            if edge.trades < 5:
                continue
            if edge.win_rate >= 65:
                lessons.append(Lesson(
                    category="edge",
                    confidence=min(0.9, 0.5 + edge.trades / 100),
                    message=f"Strong edge in '{edge.key}' regime: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Size UP in {edge.key} regime. Consider lowering confidence floor for {edge.key} by 5%.",
                ))
            elif edge.win_rate <= 35:
                lessons.append(Lesson(
                    category="leak",
                    confidence=min(0.9, 0.5 + edge.trades / 100),
                    message=f"Losing edge in '{edge.key}' regime: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"AVOID trading in {edge.key} regime. Set LLM to auto-flat when regime={edge.key}.",
                ))

        # ── Strategy edge lessons ────────────────────────────────
        for edge in edge_strategy:
            if edge.trades < 5:
                continue
            if edge.win_rate >= 60:
                lessons.append(Lesson(
                    category="edge",
                    confidence=min(0.85, 0.5 + edge.trades / 100),
                    message=f"Strategy '{edge.key}' is a winner: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Increase weight for {edge.key} in ensemble. Let LLM know this strategy is reliable.",
                ))
            elif edge.win_rate <= 35:
                lessons.append(Lesson(
                    category="leak",
                    confidence=min(0.85, 0.5 + edge.trades / 100),
                    message=f"Strategy '{edge.key}' is underperforming: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Reduce weight for {edge.key}. Consider disabling if <30% over 20+ trades.",
                ))

        # ── Symbol edge lessons ──────────────────────────────────
        for edge in edge_symbol:
            if edge.trades < 5:
                continue
            if edge.win_rate >= 65:
                lessons.append(Lesson(
                    category="edge",
                    confidence=min(0.8, 0.5 + edge.trades / 80),
                    message=f"Strong edge on {edge.key}: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Prioritize {edge.key} setups. Consider increasing position limits for this asset.",
                ))
            elif edge.win_rate <= 30:
                lessons.append(Lesson(
                    category="leak",
                    confidence=min(0.8, 0.5 + edge.trades / 80),
                    message=f"Losing money on {edge.key}: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Reduce or remove {edge.key} from watchlist. Not every asset suits the strategy.",
                ))

        # ── Time-of-day lessons ──────────────────────────────────
        winning_hours = [e for e in edge_hour if e.trades >= 3 and e.win_rate >= 65]
        losing_hours = [e for e in edge_hour if e.trades >= 3 and e.win_rate <= 30]

        if winning_hours:
            best = max(winning_hours, key=lambda x: x.total_pnl)
            lessons.append(Lesson(
                category="opportunity",
                confidence=0.6,
                message=f"Best trading hour: {best.key} UTC ({best.win_rate:.0f}% WR)",
                evidence=f"{best.wins}/{best.trades} wins, PnL: ${best.total_pnl:.2f}",
                action=f"Consider increasing LLM call frequency during {best.key} UTC window.",
            ))

        if losing_hours:
            worst = min(losing_hours, key=lambda x: x.total_pnl)
            lessons.append(Lesson(
                category="leak",
                confidence=0.6,
                message=f"Worst trading hour: {worst.key} UTC ({worst.win_rate:.0f}% WR)",
                evidence=f"{worst.wins}/{worst.trades} wins, PnL: ${worst.total_pnl:.2f}",
                action=f"Consider pausing trading or raising confidence floor during {worst.key} UTC.",
            ))

        # ── Side bias lessons ────────────────────────────────────
        for edge in edge_side:
            if edge.trades < 5:
                continue
            if edge.win_rate >= 60 and edge.total_pnl > 0:
                lessons.append(Lesson(
                    category="edge",
                    confidence=min(0.75, 0.5 + edge.trades / 100),
                    message=f"'{edge.key}' side is profitable: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"System has a {edge.key} bias. This is fine if regime supports it.",
                ))
            elif edge.win_rate <= 35:
                lessons.append(Lesson(
                    category="leak",
                    confidence=min(0.75, 0.5 + edge.trades / 100),
                    message=f"'{edge.key}' side is losing: {edge.win_rate:.0f}% WR",
                    evidence=f"{edge.wins}/{edge.trades} wins, PnL: ${edge.total_pnl:.2f}",
                    action=f"Consider biasing LLM to veto {edge.key} trades unless high conviction.",
                ))

        # ── Trigger ROI lessons ──────────────────────────────────
        high_roi_triggers = [t for t in trigger_roi if t.calls >= 5 and t.vetoes > 0]
        if high_roi_triggers:
            best_trigger = max(high_roi_triggers, key=lambda x: x.vetoes / max(x.calls, 1))
            if best_trigger.vetoes / max(best_trigger.calls, 1) > 0.3:
                lessons.append(Lesson(
                    category="edge",
                    confidence=0.7,
                    message=f"LLM trigger '{best_trigger.trigger}' has high veto rate ({best_trigger.vetoes}/{best_trigger.calls})",
                    evidence=f"This trigger is actively preventing bad trades",
                    action=f"Keep {best_trigger.trigger} trigger active. Consider reducing its cooldown.",
                ))

        low_value_triggers = [
            t for t in trigger_roi
            if t.calls >= 10 and t.vetoes == 0 and t.trigger != "unknown"
        ]
        if low_value_triggers:
            for t in low_value_triggers[:2]:
                lessons.append(Lesson(
                    category="opportunity",
                    confidence=0.5,
                    message=f"Trigger '{t.trigger}' never vetoes ({t.calls} calls, 0 vetoes)",
                    evidence=f"All {t.calls} calls resulted in 'proceed'",
                    action=f"Either increase {t.trigger} cooldown to save API cost, or the LLM needs more aggressive veto criteria.",
                ))

        # ── Memory-based lessons ─────────────────────────────────
        if memory_notes:
            recent_notes = sorted(
                memory_notes,
                key=lambda n: n.get("ts", 0) if isinstance(n, dict) else 0,
                reverse=True,
            )[:5]
            patterns = [
                n.get("text", str(n)) if isinstance(n, dict) else str(n)
                for n in recent_notes
            ]
            if patterns:
                lessons.append(Lesson(
                    category="opportunity",
                    confidence=0.5,
                    message="LLM memory patterns (most recent observations)",
                    evidence=" | ".join(patterns[:3]),
                    action="Review these patterns. Are they still valid? Update system prompt if patterns have shifted.",
                ))

        # Sort by confidence descending
        lessons.sort(key=lambda x: x.confidence, reverse=True)
        return lessons

    def _compute_throttle_recommendation(
        self,
        trigger_roi: List[TriggerROI],
        trajectory: List[WinRateWindow],
        decisions: List[Dict[str, Any]],
    ) -> ThrottleRecommendation:
        """Recommend optimal throttle settings based on trigger ROI."""
        current_hourly = int(os.getenv("LLM_MAX_CALLS_HOUR", "15"))
        current_daily = int(os.getenv("LLM_MAX_CALLS_DAY", "150"))
        current_model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

        total_calls = sum(t.calls for t in trigger_roi)
        total_vetoes = sum(t.vetoes for t in trigger_roi)

        # Analyze if we're hitting rate limits
        if decisions:
            timestamps = [d.get("ts", 0) for d in decisions if d.get("ts")]
            if len(timestamps) >= 2:
                span_hours = (max(timestamps) - min(timestamps)) / 3600
                if span_hours > 0:
                    actual_hourly_rate = len(timestamps) / span_hours
                else:
                    actual_hourly_rate = 0
            else:
                actual_hourly_rate = 0
        else:
            actual_hourly_rate = 0

        # Determine if we're throttle-limited
        hitting_limit = actual_hourly_rate > current_hourly * 0.85

        # Calculate veto rate (higher = LLM adding more value)
        veto_rate = total_vetoes / max(total_calls, 1)

        # Recommendation logic
        reasons = []

        if hitting_limit:
            rec_hourly = min(current_hourly + 15, 60)
            rec_daily = min(current_daily + 200, 800)
            reasons.append(
                f"Currently hitting rate limit ({actual_hourly_rate:.0f}/hr vs {current_hourly}/hr cap)"
            )
        elif veto_rate > 0.25:
            rec_hourly = min(current_hourly + 10, 50)
            rec_daily = min(current_daily + 150, 600)
            reasons.append(
                f"LLM has high veto rate ({veto_rate:.0%}) — it's finding bad trades to block"
            )
        elif veto_rate < 0.05 and total_calls > 50:
            rec_hourly = max(current_hourly - 5, 10)
            rec_daily = max(current_daily - 50, 100)
            reasons.append(
                f"LLM rarely vetoes ({veto_rate:.0%}) — reduce calls or make it more aggressive"
            )
        else:
            rec_hourly = current_hourly
            rec_daily = current_daily
            reasons.append("Current throttle settings appear balanced")

        # Model recommendation
        all_time = next(
            (w for w in trajectory if w.window_label == "all"), None
        )
        if all_time and all_time.total_trades >= 20 and all_time.win_rate >= 50:
            rec_model = "claude-sonnet-4-5-20250929"
            reasons.append(
                "System is profitable — upgrade to Sonnet for better regime analysis"
            )
        elif all_time and all_time.total_trades >= 20 and all_time.win_rate < 45:
            rec_model = "claude-sonnet-4-5-20250929"
            reasons.append(
                "System is losing — upgrade to Sonnet for smarter vetoes"
            )
        else:
            rec_model = current_model
            reasons.append(f"Keep current model until 20+ trades for evaluation")

        # Cost estimate
        per_call = 0.004 if "haiku" in rec_model else 0.011
        est_monthly = rec_daily * 30 * per_call

        return ThrottleRecommendation(
            current_hourly=current_hourly,
            current_daily=current_daily,
            recommended_hourly=rec_hourly,
            recommended_daily=rec_daily,
            recommended_model=rec_model,
            estimated_monthly_cost=est_monthly,
            reasoning=" | ".join(reasons),
        )

    # ── Main report generation ───────────────────────────────────

    def generate_report(self) -> EvolutionReport:
        """Generate a complete evolution report from all data sources."""
        decisions = self._load_decisions()
        trades = self._load_trades()
        memory = self._load_memory()
        quality = self._load_signal_quality()

        report = EvolutionReport(
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )

        # Compute time span
        if trades:
            timestamps = [self._parse_trade_ts(t) for t in trades]
            valid_ts = [t for t in timestamps if t > 0]
            if valid_ts:
                report.days_of_data = (max(valid_ts) - min(valid_ts)) / 86400

        report.total_decisions = len(decisions)
        report.total_trades = len(trades)
        report.memory_notes_count = len(memory)

        # Win rate trajectory
        report.win_rate_trajectory = self._compute_win_rate_trajectory(trades)

        # Edge attribution
        report.edge_by_regime = self._compute_edge_by_dimension(trades, "regime")
        report.edge_by_strategy = self._compute_edge_by_dimension(trades, "strategy")
        report.edge_by_symbol = self._compute_edge_by_dimension(trades, "symbol")
        report.edge_by_side = self._compute_edge_by_dimension(trades, "side")
        report.edge_by_hour = self._compute_edge_by_hour(trades)

        # Trigger ROI
        report.trigger_roi = self._compute_trigger_roi(decisions, trades)
        report.llm_total_calls = sum(t.calls for t in report.trigger_roi)
        report.llm_veto_count = sum(t.vetoes for t in report.trigger_roi)
        report.llm_proceed_count = sum(t.proceeds for t in report.trigger_roi)
        report.llm_estimated_cost = sum(t.estimated_cost for t in report.trigger_roi)

        # Lessons
        report.lessons = self._extract_lessons(
            report.win_rate_trajectory,
            report.edge_by_regime,
            report.edge_by_strategy,
            report.edge_by_symbol,
            report.edge_by_hour,
            report.edge_by_side,
            report.trigger_roi,
            decisions,
            memory,
        )

        # Throttle recommendation
        report.throttle_rec = self._compute_throttle_recommendation(
            report.trigger_roi,
            report.win_rate_trajectory,
            decisions,
        )

        return report

    # ── Report formatting ────────────────────────────────────────

    def format_report(self, report: EvolutionReport) -> str:
        """Format evolution report as human-readable text."""
        lines = []
        sep = "=" * 70

        lines.append(sep)
        lines.append("  STRATEGY EVOLUTION REPORT — THE STUDENT'S JOURNAL")
        lines.append(f"  Generated: {report.generated_at}")
        lines.append(f"  Data: {report.days_of_data:.1f} days | {report.total_trades} trades | {report.total_decisions} LLM decisions")
        lines.append(sep)

        # ── Win Rate Trajectory ──────────────────────────────────
        lines.append("")
        lines.append("  WIN RATE TRAJECTORY")
        lines.append("  " + "-" * 60)
        lines.append(f"  {'Window':<8} {'Trades':>7} {'Wins':>6} {'WR%':>7} {'PnL':>10} {'Avg PnL':>10}")
        lines.append("  " + "-" * 60)

        for w in report.win_rate_trajectory:
            if w.total_trades == 0:
                continue
            wr_bar = self._bar(w.win_rate, 100, 15)
            pnl_str = f"${w.total_pnl:+.2f}"
            avg_str = f"${w.avg_pnl:+.2f}"
            lines.append(
                f"  {w.window_label:<8} {w.total_trades:>7} {w.wins:>6} "
                f"{w.win_rate:>6.1f}% {pnl_str:>10} {avg_str:>10}  {wr_bar}"
            )

        # ── Edge Attribution ─────────────────────────────────────
        for label, edges in [
            ("BY REGIME", report.edge_by_regime),
            ("BY STRATEGY", report.edge_by_strategy),
            ("BY SYMBOL", report.edge_by_symbol),
            ("BY SIDE", report.edge_by_side),
        ]:
            if not edges:
                continue
            lines.append("")
            lines.append(f"  EDGE {label}")
            lines.append("  " + "-" * 60)
            lines.append(f"  {'Key':<20} {'Trades':>7} {'WR%':>7} {'PnL':>10} {'Avg':>10}")
            lines.append("  " + "-" * 60)

            for e in edges[:10]:
                if e.trades == 0:
                    continue
                marker = "+" if e.total_pnl > 0 else "-" if e.total_pnl < 0 else " "
                lines.append(
                    f" {marker}{e.key:<20} {e.trades:>7} {e.win_rate:>6.1f}% "
                    f"${e.total_pnl:>+9.2f} ${e.avg_pnl:>+9.2f}"
                )

        # ── Best/Worst Hours ─────────────────────────────────────
        if report.edge_by_hour:
            active_hours = [h for h in report.edge_by_hour if h.trades >= 2]
            if active_hours:
                lines.append("")
                lines.append("  EDGE BY HOUR (UTC)")
                lines.append("  " + "-" * 60)
                for e in active_hours[:6]:
                    marker = "+" if e.total_pnl > 0 else "-"
                    lines.append(
                        f" {marker}{e.key:<8} {e.trades:>4} trades  "
                        f"{e.win_rate:>5.1f}% WR  ${e.total_pnl:>+8.2f}"
                    )

        # ── LLM Trigger Analysis ─────────────────────────────────
        if report.trigger_roi:
            lines.append("")
            lines.append("  LLM TRIGGER ANALYSIS")
            lines.append("  " + "-" * 60)
            lines.append(
                f"  Total calls: {report.llm_total_calls} | "
                f"Vetoes: {report.llm_veto_count} | "
                f"Proceeds: {report.llm_proceed_count} | "
                f"Est. cost: ${report.llm_estimated_cost:.2f}"
            )
            lines.append("")
            lines.append(f"  {'Trigger':<28} {'Calls':>6} {'Vetoes':>7} {'Proceeds':>9} {'Cost':>7}")
            lines.append("  " + "-" * 60)

            for t in report.trigger_roi:
                if t.calls == 0:
                    continue
                lines.append(
                    f"  {t.trigger:<28} {t.calls:>6} {t.vetoes:>7} "
                    f"{t.proceeds:>9} ${t.estimated_cost:>6.3f}"
                )

        # ── Throttle Recommendation ──────────────────────────────
        if report.throttle_rec:
            rec = report.throttle_rec
            lines.append("")
            lines.append("  THROTTLE RECOMMENDATION")
            lines.append("  " + "-" * 60)
            lines.append(f"  Current:     {rec.current_hourly}/hr, {rec.current_daily}/day")
            lines.append(f"  Recommended: {rec.recommended_hourly}/hr, {rec.recommended_daily}/day")
            lines.append(f"  Model:       {rec.recommended_model}")
            lines.append(f"  Est. cost:   ${rec.estimated_monthly_cost:.0f}/month")
            lines.append(f"  Reasoning:   {rec.reasoning}")

        # ── Lessons ──────────────────────────────────────────────
        if report.lessons:
            lines.append("")
            lines.append(sep)
            lines.append("  LESSONS LEARNED (sorted by confidence)")
            lines.append(sep)

            for i, lesson in enumerate(report.lessons, 1):
                icon = {
                    "edge": "[EDGE]",
                    "leak": "[LEAK]",
                    "opportunity": "[OPPY]",
                    "risk": "[RISK]",
                }
                cat = icon.get(lesson.category, f"[{lesson.category.upper()}]")
                lines.append(f"")
                lines.append(f"  {i}. {cat} {lesson.message}")
                lines.append(f"     Evidence: {lesson.evidence}")
                lines.append(f"     Action:   {lesson.action}")
                lines.append(f"     Confidence: {lesson.confidence:.0%}")

        # ── Growth Mindset Footer ────────────────────────────────
        lines.append("")
        lines.append(sep)
        lines.append("  THE STUDENT'S CREED")
        lines.append(sep)
        lines.append("  1. Protect capital FIRST — edge means nothing if you blow up")
        lines.append("  2. Size UP where you have proven edge, not where you hope")
        lines.append("  3. Cut dimensions that leak — not every market/regime suits you")
        lines.append("  4. The LLM is a TOOL — calibrate its throttle to match its value")
        lines.append("  5. Review this report DAILY — a student who doesn't study fails")
        lines.append(sep)

        return "\n".join(lines)

    # ── Utility ──────────────────────────────────────────────────

    @staticmethod
    def _parse_trade_ts(trade: Dict[str, str]) -> float:
        """Extract timestamp from a trade row."""
        for key in ("timestamp", "ts", "close_ts", "open_ts", "time"):
            val = trade.get(key, "")
            if val:
                try:
                    return float(val)
                except ValueError:
                    # Try ISO format
                    try:
                        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                        return dt.timestamp()
                    except (ValueError, TypeError):
                        continue
        return 0.0

    @staticmethod
    def _parse_float(val: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _bar(value: float, max_val: float, width: int = 15) -> str:
        """Create a simple ASCII bar chart segment."""
        filled = int(value / max(max_val, 1) * width)
        filled = max(0, min(filled, width))
        return "|" + "#" * filled + "." * (width - filled) + "|"
