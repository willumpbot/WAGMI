"""
Counterfactual Learning Engine: "What-if rewinding" for trade decisions.

This module tracks what WOULD have happened with different decisions, answering:
  - "If we hadn't vetoed that trade, what would have happened?"
  - "If we'd used 2x leverage instead of 5x, what would the outcome be?"
  - "If we'd exited at TP1 instead of holding to TP2, how much better/worse?"

For every decision point, the engine records the actual action AND the
counterfactual alternative. Once price data resolves, it computes the
delta: did we make the right call?

Over time, this builds a dataset of decision quality that feeds back into:
  - Veto calibration (are we vetoing good trades?)
  - Sizing optimization (would smaller/larger positions have been better?)
  - Exit timing (TP1 vs TP2 vs trailing stop)
  - Actionable learning insights for the LLM meta-brain

Usage:
    from analytics.counterfactual import get_counterfactual_engine

    engine = get_counterfactual_engine()

    # Record a vetoed trade
    engine.record_veto(
        symbol="BTC/USDT", side="long", entry_price=50000,
        sl_price=49000, tp1_price=51500, tp2_price=53000,
        confidence=72.0, reason="LLM veto: regime mismatch"
    )

    # Later, resolve with current prices
    engine.resolve_pending({"BTC/USDT": 51800}, lookback_hours=24)

    # Get insights
    print(engine.get_counterfactual_report())
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.counterfactual")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CounterfactualScenario:
    """A single counterfactual: what actually happened vs what could have."""
    id: str
    timestamp: float
    symbol: str
    scenario_type: str  # "veto_override", "leverage_change", "exit_timing", "entry_skip"
    actual_action: str  # What actually happened
    counterfactual_action: str  # What could have happened
    actual_pnl: float
    counterfactual_pnl: float  # Computed from price data once resolved
    delta: float  # counterfactual_pnl - actual_pnl
    resolved: bool = False  # True once price data confirms the outcome
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CounterfactualScenario":
        """Deserialize from a dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", 0.0),
            symbol=data.get("symbol", ""),
            scenario_type=data.get("scenario_type", ""),
            actual_action=data.get("actual_action", ""),
            counterfactual_action=data.get("counterfactual_action", ""),
            actual_pnl=data.get("actual_pnl", 0.0),
            counterfactual_pnl=data.get("counterfactual_pnl", 0.0),
            delta=data.get("delta", 0.0),
            resolved=data.get("resolved", False),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class CounterfactualEngine:
    """
    Records, resolves, and analyzes counterfactual trade scenarios.

    Thread-safe. Persists scenarios to JSON. Provides actionable insights
    about whether decisions (vetoes, sizing, exit timing) were optimal.
    """

    # Maximum resolved scenarios to keep in memory / on disk before cleanup
    MAX_RESOLVED_SCENARIOS = 500
    # Scenarios older than this are eligible for cleanup (seconds)
    CLEANUP_AGE_SECONDS = 30 * 86400  # 30 days

    def __init__(self, data_dir: str = "data/counterfactuals"):
        self._data_dir = data_dir
        self._scenarios_file = os.path.join(data_dir, "scenarios.json")
        self._lock = threading.Lock()
        self._scenarios: List[CounterfactualScenario] = []

        os.makedirs(data_dir, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_veto(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        tp2_price: float,
        confidence: float,
        reason: str,
    ) -> str:
        """Record a vetoed trade for later resolution.

        The counterfactual asks: if we had NOT vetoed, what would the PnL
        have been?  We store the trade parameters and resolve later when
        price data shows whether TP1/TP2 or SL was hit first.

        Returns:
            The scenario id.
        """
        scenario_id = self._make_id()

        scenario = CounterfactualScenario(
            id=scenario_id,
            timestamp=time.time(),
            symbol=symbol,
            scenario_type="veto_override",
            actual_action=f"vetoed_{side}",
            counterfactual_action=f"entered_{side}",
            actual_pnl=0.0,  # We didn't trade, so PnL is 0
            counterfactual_pnl=0.0,  # Unknown until resolved
            delta=0.0,
            resolved=False,
            metadata={
                "side": side,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp1_price": tp1_price,
                "tp2_price": tp2_price,
                "confidence": confidence,
                "reason": reason,
            },
        )

        with self._lock:
            self._scenarios.append(scenario)
            self._save()

        logger.info(
            "[COUNTERFACTUAL] Recorded veto scenario %s: %s %s @ %.2f "
            "(SL=%.2f, TP1=%.2f, TP2=%.2f, conf=%.1f%%) reason=%s",
            scenario_id, side, symbol, entry_price,
            sl_price, tp1_price, tp2_price, confidence, reason,
        )
        return scenario_id

    def record_alternative_sizing(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        actual_qty: float,
        actual_leverage: float,
        alternative_leverage: float,
    ) -> str:
        """Record what would have happened with different sizing / leverage.

        The actual PnL will be filled in when the position closes; the
        counterfactual PnL is scaled proportionally by the leverage ratio.

        Returns:
            The scenario id.
        """
        scenario_id = self._make_id()

        leverage_ratio = alternative_leverage / max(actual_leverage, 0.01)

        scenario = CounterfactualScenario(
            id=scenario_id,
            timestamp=time.time(),
            symbol=symbol,
            scenario_type="leverage_change",
            actual_action=f"{side}_{actual_leverage:.1f}x",
            counterfactual_action=f"{side}_{alternative_leverage:.1f}x",
            actual_pnl=0.0,  # Filled when position closes
            counterfactual_pnl=0.0,  # Computed as actual_pnl * leverage_ratio
            delta=0.0,
            resolved=False,
            metadata={
                "side": side,
                "entry_price": entry_price,
                "actual_qty": actual_qty,
                "actual_leverage": actual_leverage,
                "alternative_leverage": alternative_leverage,
                "leverage_ratio": leverage_ratio,
            },
        )

        with self._lock:
            self._scenarios.append(scenario)
            self._save()

        logger.info(
            "[COUNTERFACTUAL] Recorded sizing scenario %s: %s %s "
            "actual=%.1fx vs alt=%.1fx (ratio=%.2f)",
            scenario_id, side, symbol,
            actual_leverage, alternative_leverage, leverage_ratio,
        )
        return scenario_id

    def record_exit_alternative(
        self,
        symbol: str,
        actual_exit_action: str,
        actual_exit_price: float,
        tp1_price: float,
        tp2_price: float,
        entry_price: float,
        actual_pnl: float,
    ) -> str:
        """Record what would have happened with different exit timing.

        Compares the actual exit against exiting at TP1 and TP2.

        Returns:
            The scenario id.
        """
        scenario_id = self._make_id()

        # Determine side from entry vs TP1 relationship
        side = "long" if tp1_price > entry_price else "short"

        # Compute counterfactual PnLs for TP1 and TP2 exits
        if side == "long":
            pnl_at_tp1 = tp1_price - entry_price
            pnl_at_tp2 = tp2_price - entry_price
        else:
            pnl_at_tp1 = entry_price - tp1_price
            pnl_at_tp2 = entry_price - tp2_price

        # Normalize to percentage of entry for comparability
        pnl_pct_actual = (actual_pnl / max(entry_price, 0.01)) * 100
        pnl_pct_tp1 = (pnl_at_tp1 / max(entry_price, 0.01)) * 100
        pnl_pct_tp2 = (pnl_at_tp2 / max(entry_price, 0.01)) * 100

        # Pick the most relevant counterfactual based on what actually happened
        if "tp1" in actual_exit_action.lower():
            # Exited at TP1 -- counterfactual is "what if we held to TP2?"
            cf_action = "hold_to_tp2"
            cf_pnl = pnl_pct_tp2
        elif "tp2" in actual_exit_action.lower():
            # Exited at TP2 -- counterfactual is "what if we exited at TP1?"
            cf_action = "exit_at_tp1"
            cf_pnl = pnl_pct_tp1
        elif "sl" in actual_exit_action.lower() or "stop" in actual_exit_action.lower():
            # Hit stop loss -- counterfactual is "what if TP1 was reachable?"
            cf_action = "exit_at_tp1"
            cf_pnl = pnl_pct_tp1
        else:
            # Generic exit -- compare against both and pick the best
            cf_action = "exit_at_tp1" if abs(pnl_pct_tp1) > abs(pnl_pct_tp2) else "hold_to_tp2"
            cf_pnl = pnl_pct_tp1 if cf_action == "exit_at_tp1" else pnl_pct_tp2

        scenario = CounterfactualScenario(
            id=scenario_id,
            timestamp=time.time(),
            symbol=symbol,
            scenario_type="exit_timing",
            actual_action=actual_exit_action,
            counterfactual_action=cf_action,
            actual_pnl=pnl_pct_actual,
            counterfactual_pnl=cf_pnl,
            delta=cf_pnl - pnl_pct_actual,
            resolved=True,  # Exit alternatives are immediately resolved
            metadata={
                "side": side,
                "entry_price": entry_price,
                "actual_exit_price": actual_exit_price,
                "tp1_price": tp1_price,
                "tp2_price": tp2_price,
                "actual_pnl_raw": actual_pnl,
                "pnl_at_tp1_pct": round(pnl_pct_tp1, 4),
                "pnl_at_tp2_pct": round(pnl_pct_tp2, 4),
            },
        )

        with self._lock:
            self._scenarios.append(scenario)
            self._save()

        logger.info(
            "[COUNTERFACTUAL] Recorded exit scenario %s: %s actual=%s (%.2f%%) "
            "vs %s (%.2f%%) delta=%.2f%%",
            scenario_id, symbol, actual_exit_action, pnl_pct_actual,
            cf_action, cf_pnl, scenario.delta,
        )
        return scenario_id

    def update_sizing_outcome(
        self, scenario_id: str, actual_pnl: float
    ) -> bool:
        """Update a leverage_change scenario once the position closes.

        Returns True if the scenario was found and updated.
        """
        with self._lock:
            scenario = self._find_by_id(scenario_id)
            if scenario is None or scenario.scenario_type != "leverage_change":
                return False

            leverage_ratio = scenario.metadata.get("leverage_ratio", 1.0)
            scenario.actual_pnl = actual_pnl
            scenario.counterfactual_pnl = actual_pnl * leverage_ratio
            scenario.delta = scenario.counterfactual_pnl - scenario.actual_pnl
            scenario.resolved = True
            self._save()

        logger.info(
            "[COUNTERFACTUAL] Resolved sizing scenario %s: actual=%.2f, "
            "counterfactual=%.2f, delta=%.2f",
            scenario_id, actual_pnl,
            scenario.counterfactual_pnl, scenario.delta,
        )
        return True

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_pending(
        self,
        current_prices: Dict[str, float],
        lookback_hours: int = 24,
    ) -> int:
        """Resolve pending counterfactual scenarios using current price data.

        For vetoed trades: checks whether price moved from entry to TP1/TP2
        (veto was wrong -- we missed a winner) or to SL (veto was correct --
        we dodged a loser).

        For simplicity, this uses the current price as a proxy.  A more
        sophisticated implementation could ingest OHLCV candles to determine
        the exact price path within the lookback window.

        Args:
            current_prices: {symbol: current_price} mapping.
            lookback_hours: Only resolve scenarios younger than this.

        Returns:
            Number of scenarios resolved in this call.
        """
        now = time.time()
        cutoff = now - lookback_hours * 3600
        resolved_count = 0

        with self._lock:
            for scenario in self._scenarios:
                if scenario.resolved:
                    continue
                if scenario.timestamp < cutoff:
                    # Too old to resolve with current snapshot; mark as
                    # expired rather than leaving it pending forever.
                    self._expire_scenario(scenario)
                    resolved_count += 1
                    continue

                if scenario.scenario_type == "veto_override":
                    price = current_prices.get(scenario.symbol)
                    if price is None:
                        continue
                    if self._resolve_veto(scenario, price):
                        resolved_count += 1

            if resolved_count > 0:
                self._save()

        if resolved_count > 0:
            logger.info(
                "[COUNTERFACTUAL] Resolved %d pending scenarios", resolved_count
            )
        return resolved_count

    def _resolve_veto(self, scenario: CounterfactualScenario, current_price: float) -> bool:
        """Resolve a single veto scenario given the current price.

        Logic:
          - For a long trade: if price rose from entry to >= TP1, the veto
            was wrong (we missed profit). If it fell to <= SL, veto correct.
          - For a short trade: if price fell from entry to <= TP1, veto wrong.
            If it rose to >= SL, veto correct.
          - If price is between SL and TP1, the scenario is not yet resolved.

        Returns True if the scenario was resolved.
        """
        meta = scenario.metadata
        entry = meta.get("entry_price", 0.0)
        sl = meta.get("sl_price", 0.0)
        tp1 = meta.get("tp1_price", 0.0)
        tp2 = meta.get("tp2_price", 0.0)
        side = meta.get("side", "long")

        if entry <= 0:
            return False

        if side == "long":
            # Long: price going up is good for the counterfactual trade
            if current_price >= tp2:
                # Hit TP2 -- veto was very wrong, big missed profit
                pnl_pct = ((tp2 - entry) / entry) * 100
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "tp2"
            elif current_price >= tp1:
                # Hit TP1 -- veto was wrong, moderate missed profit
                pnl_pct = ((tp1 - entry) / entry) * 100
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "tp1"
            elif current_price <= sl:
                # Hit SL -- veto was correct, dodged a loss
                pnl_pct = ((sl - entry) / entry) * 100
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "sl"
            else:
                # Price is between SL and TP1 -- not yet resolved
                return False
        else:
            # Short: price going down is good for the counterfactual trade
            if current_price <= tp2:
                pnl_pct = ((entry - tp2) / entry) * 100
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "tp2"
            elif current_price <= tp1:
                pnl_pct = ((entry - tp1) / entry) * 100
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "tp1"
            elif current_price >= sl:
                pnl_pct = ((entry - sl) / entry) * 100  # Negative for short SL
                scenario.counterfactual_pnl = pnl_pct
                scenario.metadata["hit"] = "sl"
            else:
                return False

        # Actual PnL is 0 because we vetoed (didn't trade)
        scenario.actual_pnl = 0.0
        scenario.delta = scenario.counterfactual_pnl - scenario.actual_pnl
        scenario.resolved = True

        logger.info(
            "[COUNTERFACTUAL] Veto resolved %s: %s %s hit %s, "
            "counterfactual PnL=%.2f%% (veto was %s)",
            scenario.id, scenario.symbol, side,
            scenario.metadata.get("hit", "?"),
            scenario.counterfactual_pnl,
            "correct" if scenario.counterfactual_pnl < 0 else "wrong",
        )
        return True

    def _expire_scenario(self, scenario: CounterfactualScenario) -> None:
        """Mark a scenario as expired -- too old to resolve reliably."""
        scenario.resolved = True
        scenario.metadata["expired"] = True
        scenario.metadata["expiry_reason"] = "exceeded_lookback_window"
        # Leave PnLs at 0 so it doesn't skew statistics
        scenario.counterfactual_pnl = 0.0
        scenario.delta = 0.0

    # ------------------------------------------------------------------
    # Analysis: veto accuracy
    # ------------------------------------------------------------------

    def get_veto_accuracy(self) -> Dict[str, Any]:
        """Analyze what percentage of vetoes were correct (avoided losses).

        Returns:
            {
                "total_vetoes": int,
                "resolved": int,
                "correct_vetoes": int,      # Veto dodged a loss (CF PnL < 0)
                "wrong_vetoes": int,         # Veto missed a winner (CF PnL > 0)
                "neutral_vetoes": int,       # CF PnL ~0 or expired
                "accuracy_pct": float,       # correct / (correct + wrong) * 100
                "missed_profit_total": float, # Sum of positive CF PnLs (%)
                "dodged_loss_total": float,   # Sum of negative CF PnLs (%)
                "avg_missed_profit": float,
                "avg_dodged_loss": float,
                "net_veto_value": float,      # dodged_loss_total + missed_profit_total
                "by_confidence": dict,        # Veto accuracy bucketed by confidence
            }
        """
        with self._lock:
            vetos = [
                s for s in self._scenarios
                if s.scenario_type == "veto_override"
            ]

        resolved = [s for s in vetos if s.resolved and not s.metadata.get("expired")]
        correct = [s for s in resolved if s.counterfactual_pnl < -0.01]
        wrong = [s for s in resolved if s.counterfactual_pnl > 0.01]
        neutral = [s for s in resolved if abs(s.counterfactual_pnl) <= 0.01]

        missed_profits = [s.counterfactual_pnl for s in wrong]
        dodged_losses = [s.counterfactual_pnl for s in correct]

        total_judged = len(correct) + len(wrong)
        accuracy = (len(correct) / total_judged * 100) if total_judged > 0 else 0.0

        # Bucket by confidence to see if we're vetoing the right confidence levels
        by_confidence = self._bucket_vetos_by_confidence(resolved)

        return {
            "total_vetoes": len(vetos),
            "resolved": len(resolved),
            "correct_vetoes": len(correct),
            "wrong_vetoes": len(wrong),
            "neutral_vetoes": len(neutral),
            "accuracy_pct": round(accuracy, 1),
            "missed_profit_total": round(sum(missed_profits), 2),
            "dodged_loss_total": round(sum(dodged_losses), 2),
            "avg_missed_profit": (
                round(sum(missed_profits) / len(missed_profits), 2)
                if missed_profits else 0.0
            ),
            "avg_dodged_loss": (
                round(sum(dodged_losses) / len(dodged_losses), 2)
                if dodged_losses else 0.0
            ),
            "net_veto_value": round(
                sum(dodged_losses) + sum(missed_profits), 2
            ),
            "by_confidence": by_confidence,
        }

    def _bucket_vetos_by_confidence(
        self, resolved_vetos: List[CounterfactualScenario]
    ) -> Dict[str, Dict[str, Any]]:
        """Group veto outcomes by the confidence level of the vetoed signal."""
        buckets: Dict[str, List[CounterfactualScenario]] = {
            "low_50_60": [],
            "mid_60_70": [],
            "high_70_80": [],
            "very_high_80+": [],
        }

        for s in resolved_vetos:
            conf = s.metadata.get("confidence", 0.0)
            if conf < 60:
                buckets["low_50_60"].append(s)
            elif conf < 70:
                buckets["mid_60_70"].append(s)
            elif conf < 80:
                buckets["high_70_80"].append(s)
            else:
                buckets["very_high_80+"].append(s)

        result = {}
        for label, scenarios in buckets.items():
            if not scenarios:
                continue
            correct = sum(1 for s in scenarios if s.counterfactual_pnl < -0.01)
            wrong = sum(1 for s in scenarios if s.counterfactual_pnl > 0.01)
            total = correct + wrong
            result[label] = {
                "count": len(scenarios),
                "correct": correct,
                "wrong": wrong,
                "accuracy_pct": round(
                    correct / total * 100 if total > 0 else 0.0, 1
                ),
            }
        return result

    # ------------------------------------------------------------------
    # Analysis: sizing insights
    # ------------------------------------------------------------------

    def get_sizing_insights(self) -> Dict[str, Any]:
        """Analyze whether larger or smaller positions performed better.

        Returns:
            {
                "total_scenarios": int,
                "resolved": int,
                "higher_leverage_better": int,  # Alternative outperformed actual
                "lower_leverage_better": int,
                "avg_delta": float,
                "by_leverage_pair": dict,       # Grouped by actual->alternative
            }
        """
        with self._lock:
            sizing = [
                s for s in self._scenarios
                if s.scenario_type == "leverage_change" and s.resolved
            ]

        if not sizing:
            return {
                "total_scenarios": 0,
                "resolved": 0,
                "higher_leverage_better": 0,
                "lower_leverage_better": 0,
                "avg_delta": 0.0,
                "by_leverage_pair": {},
            }

        higher_better = 0
        lower_better = 0
        deltas = []
        by_pair: Dict[str, List[float]] = {}

        for s in sizing:
            actual_lev = s.metadata.get("actual_leverage", 0.0)
            alt_lev = s.metadata.get("alternative_leverage", 0.0)
            pair_key = f"{actual_lev:.0f}x_vs_{alt_lev:.0f}x"

            deltas.append(s.delta)
            by_pair.setdefault(pair_key, []).append(s.delta)

            if alt_lev > actual_lev and s.delta > 0:
                higher_better += 1
            elif alt_lev < actual_lev and s.delta > 0:
                lower_better += 1
            elif alt_lev > actual_lev and s.delta < 0:
                lower_better += 1
            elif alt_lev < actual_lev and s.delta < 0:
                higher_better += 1

        pair_summary = {}
        for pair, pair_deltas in by_pair.items():
            pair_summary[pair] = {
                "count": len(pair_deltas),
                "avg_delta": round(sum(pair_deltas) / len(pair_deltas), 4),
                "alt_better_pct": round(
                    sum(1 for d in pair_deltas if d > 0) / len(pair_deltas) * 100, 1
                ),
            }

        return {
            "total_scenarios": len(sizing),
            "resolved": len(sizing),
            "higher_leverage_better": higher_better,
            "lower_leverage_better": lower_better,
            "avg_delta": round(sum(deltas) / len(deltas), 4) if deltas else 0.0,
            "by_leverage_pair": pair_summary,
        }

    # ------------------------------------------------------------------
    # Analysis: exit timing insights
    # ------------------------------------------------------------------

    def get_exit_insights(self) -> Dict[str, Any]:
        """Analyze whether holding to TP2 was better than exiting at TP1.

        Returns:
            {
                "total_scenarios": int,
                "tp1_exits": int,
                "tp2_exits": int,
                "sl_exits": int,
                "holding_to_tp2_better_pct": float,
                "avg_delta_tp1_vs_tp2": float,
                "avg_actual_pnl": float,
                "avg_counterfactual_pnl": float,
            }
        """
        with self._lock:
            exits = [
                s for s in self._scenarios
                if s.scenario_type == "exit_timing" and s.resolved
            ]

        if not exits:
            return {
                "total_scenarios": 0,
                "tp1_exits": 0,
                "tp2_exits": 0,
                "sl_exits": 0,
                "holding_to_tp2_better_pct": 0.0,
                "avg_delta_tp1_vs_tp2": 0.0,
                "avg_actual_pnl": 0.0,
                "avg_counterfactual_pnl": 0.0,
            }

        tp1_exits = [
            s for s in exits if "tp1" in s.actual_action.lower()
        ]
        tp2_exits = [
            s for s in exits if "tp2" in s.actual_action.lower()
        ]
        sl_exits = [
            s for s in exits
            if "sl" in s.actual_action.lower() or "stop" in s.actual_action.lower()
        ]

        # For TP1 exits, the counterfactual was "hold to TP2"
        # A positive delta means holding to TP2 would have been better
        tp1_with_positive_delta = sum(1 for s in tp1_exits if s.delta > 0)
        holding_better_pct = (
            (tp1_with_positive_delta / len(tp1_exits) * 100)
            if tp1_exits else 0.0
        )

        deltas = [s.delta for s in exits]
        actual_pnls = [s.actual_pnl for s in exits]
        cf_pnls = [s.counterfactual_pnl for s in exits]

        return {
            "total_scenarios": len(exits),
            "tp1_exits": len(tp1_exits),
            "tp2_exits": len(tp2_exits),
            "sl_exits": len(sl_exits),
            "holding_to_tp2_better_pct": round(holding_better_pct, 1),
            "avg_delta_tp1_vs_tp2": (
                round(
                    sum(s.delta for s in tp1_exits) / len(tp1_exits), 4
                ) if tp1_exits else 0.0
            ),
            "avg_actual_pnl": round(sum(actual_pnls) / len(actual_pnls), 4),
            "avg_counterfactual_pnl": round(sum(cf_pnls) / len(cf_pnls), 4),
        }

    # ------------------------------------------------------------------
    # Reports and insights
    # ------------------------------------------------------------------

    def get_counterfactual_report(self) -> str:
        """Generate a full human-readable report of counterfactual analysis."""
        lines = []
        sep = "=" * 70

        lines.append(sep)
        lines.append("  COUNTERFACTUAL LEARNING ENGINE REPORT")
        lines.append(sep)

        with self._lock:
            total = len(self._scenarios)
            pending = sum(1 for s in self._scenarios if not s.resolved)
            resolved = total - pending

        lines.append(f"  Total scenarios: {total} | Resolved: {resolved} | Pending: {pending}")
        lines.append("")

        # --- Veto analysis ---
        veto_stats = self.get_veto_accuracy()
        lines.append("  VETO ANALYSIS")
        lines.append("  " + "-" * 60)
        if veto_stats["total_vetoes"] > 0:
            lines.append(f"  Total vetoes recorded:  {veto_stats['total_vetoes']}")
            lines.append(f"  Resolved:               {veto_stats['resolved']}")
            lines.append(f"  Correct (dodged loss):  {veto_stats['correct_vetoes']}")
            lines.append(f"  Wrong (missed profit):  {veto_stats['wrong_vetoes']}")
            lines.append(f"  Neutral / expired:      {veto_stats['neutral_vetoes']}")
            lines.append(f"  Veto accuracy:          {veto_stats['accuracy_pct']:.1f}%")
            lines.append(f"  Avg dodged loss:        {veto_stats['avg_dodged_loss']:+.2f}%")
            lines.append(f"  Avg missed profit:      {veto_stats['avg_missed_profit']:+.2f}%")
            lines.append(f"  Net veto value:         {veto_stats['net_veto_value']:+.2f}%")

            if veto_stats["by_confidence"]:
                lines.append("")
                lines.append("  Veto accuracy by signal confidence:")
                for bucket, data in sorted(veto_stats["by_confidence"].items()):
                    lines.append(
                        f"    {bucket:<20} {data['count']:>3} vetoes, "
                        f"accuracy={data['accuracy_pct']:.0f}% "
                        f"(correct={data['correct']}, wrong={data['wrong']})"
                    )
        else:
            lines.append("  No veto scenarios recorded yet.")
        lines.append("")

        # --- Sizing analysis ---
        sizing_stats = self.get_sizing_insights()
        lines.append("  SIZING / LEVERAGE ANALYSIS")
        lines.append("  " + "-" * 60)
        if sizing_stats["total_scenarios"] > 0:
            lines.append(f"  Total scenarios:        {sizing_stats['total_scenarios']}")
            lines.append(f"  Higher leverage better: {sizing_stats['higher_leverage_better']}")
            lines.append(f"  Lower leverage better:  {sizing_stats['lower_leverage_better']}")
            lines.append(f"  Avg PnL delta:          {sizing_stats['avg_delta']:+.4f}")

            if sizing_stats["by_leverage_pair"]:
                lines.append("")
                for pair, data in sizing_stats["by_leverage_pair"].items():
                    lines.append(
                        f"    {pair:<20} {data['count']:>3} trades, "
                        f"avg delta={data['avg_delta']:+.4f}, "
                        f"alt better={data['alt_better_pct']:.0f}%"
                    )
        else:
            lines.append("  No sizing scenarios recorded yet.")
        lines.append("")

        # --- Exit timing analysis ---
        exit_stats = self.get_exit_insights()
        lines.append("  EXIT TIMING ANALYSIS")
        lines.append("  " + "-" * 60)
        if exit_stats["total_scenarios"] > 0:
            lines.append(f"  Total scenarios:        {exit_stats['total_scenarios']}")
            lines.append(f"  TP1 exits:              {exit_stats['tp1_exits']}")
            lines.append(f"  TP2 exits:              {exit_stats['tp2_exits']}")
            lines.append(f"  SL exits:               {exit_stats['sl_exits']}")
            lines.append(
                f"  Holding to TP2 better:  {exit_stats['holding_to_tp2_better_pct']:.1f}% of the time"
            )
            lines.append(f"  Avg actual PnL:         {exit_stats['avg_actual_pnl']:+.4f}%")
            lines.append(f"  Avg counterfactual PnL: {exit_stats['avg_counterfactual_pnl']:+.4f}%")
        else:
            lines.append("  No exit timing scenarios recorded yet.")
        lines.append("")

        # --- Learning insights ---
        insights = self.get_learning_insights()
        if insights:
            lines.append("  ACTIONABLE INSIGHTS")
            lines.append("  " + "-" * 60)
            for i, insight in enumerate(insights, 1):
                lines.append(f"  {i}. {insight}")
            lines.append("")

        lines.append(sep)
        return "\n".join(lines)

    def get_learning_insights(self) -> List[str]:
        """Extract actionable insights from counterfactual data.

        Returns a list of human-readable insight strings, ordered by
        importance, that can be fed to the LLM meta-brain.
        """
        insights: List[str] = []

        # --- Veto insights ---
        veto_stats = self.get_veto_accuracy()
        if veto_stats["resolved"] >= 5:
            acc = veto_stats["accuracy_pct"]
            if acc >= 70:
                insights.append(
                    f"Veto system is highly accurate ({acc:.0f}%). "
                    f"Trust it -- it has dodged {veto_stats['correct_vetoes']} losses."
                )
            elif acc >= 50:
                insights.append(
                    f"Veto system is moderately accurate ({acc:.0f}%). "
                    f"Consider raising the veto confidence threshold to reduce wrong vetoes."
                )
            elif acc < 50:
                insights.append(
                    f"WARNING: Veto system is net-negative ({acc:.0f}% accuracy). "
                    f"It is blocking more winners than losers. Review veto criteria."
                )

            net_value = veto_stats["net_veto_value"]
            if net_value < -1.0:
                insights.append(
                    f"Vetoes have a net-negative value of {net_value:+.2f}%. "
                    f"Consider loosening veto criteria or switching to advisory mode."
                )
            elif net_value > 1.0:
                insights.append(
                    f"Vetoes have a net-positive value of {net_value:+.2f}%. "
                    f"The veto system is saving money."
                )

            # Confidence-bucketed insights
            by_conf = veto_stats.get("by_confidence", {})
            for bucket, data in by_conf.items():
                if data["count"] >= 3 and data["accuracy_pct"] < 40:
                    insights.append(
                        f"Vetoes in the {bucket} confidence range are mostly wrong "
                        f"({data['accuracy_pct']:.0f}% accuracy). "
                        f"Consider allowing these trades through."
                    )
                elif data["count"] >= 3 and data["accuracy_pct"] > 80:
                    insights.append(
                        f"Vetoes in the {bucket} confidence range are very accurate "
                        f"({data['accuracy_pct']:.0f}%). Good veto calibration here."
                    )

        # --- Sizing insights ---
        sizing_stats = self.get_sizing_insights()
        if sizing_stats["total_scenarios"] >= 5:
            avg_delta = sizing_stats["avg_delta"]
            higher = sizing_stats["higher_leverage_better"]
            lower = sizing_stats["lower_leverage_better"]

            if higher > lower * 1.5:
                insights.append(
                    f"Higher leverage tends to outperform ({higher} vs {lower} scenarios). "
                    f"Consider increasing base leverage by 0.5-1x."
                )
            elif lower > higher * 1.5:
                insights.append(
                    f"Lower leverage tends to outperform ({lower} vs {higher} scenarios). "
                    f"Consider reducing leverage to improve risk-adjusted returns."
                )
            else:
                insights.append(
                    f"Leverage impact is mixed (higher better: {higher}, lower better: {lower}). "
                    f"Current sizing appears balanced."
                )

        # --- Exit timing insights ---
        exit_stats = self.get_exit_insights()
        if exit_stats["total_scenarios"] >= 5:
            hold_pct = exit_stats["holding_to_tp2_better_pct"]
            if hold_pct > 60:
                insights.append(
                    f"Holding to TP2 was better {hold_pct:.0f}% of the time. "
                    f"Consider being more patient with exits."
                )
            elif hold_pct < 40:
                insights.append(
                    f"Exiting at TP1 was better {100 - hold_pct:.0f}% of the time. "
                    f"Consider taking profits earlier."
                )
            else:
                insights.append(
                    f"TP1 vs TP2 exit performance is balanced ({hold_pct:.0f}% favoring TP2). "
                    f"Current exit strategy appears calibrated."
                )

        if not insights:
            insights.append(
                "Insufficient counterfactual data for insights. "
                "Need at least 5 resolved scenarios per category."
            )

        return insights

    # ------------------------------------------------------------------
    # Statistics summary (for external consumers)
    # ------------------------------------------------------------------

    def get_summary_stats(self) -> Dict[str, Any]:
        """Return a compact summary suitable for LLM context injection."""
        with self._lock:
            total = len(self._scenarios)
            pending = sum(1 for s in self._scenarios if not s.resolved)

        veto_stats = self.get_veto_accuracy()
        sizing_stats = self.get_sizing_insights()
        exit_stats = self.get_exit_insights()

        return {
            "total_scenarios": total,
            "pending": pending,
            "veto_accuracy_pct": veto_stats.get("accuracy_pct", 0.0),
            "veto_net_value": veto_stats.get("net_veto_value", 0.0),
            "sizing_avg_delta": sizing_stats.get("avg_delta", 0.0),
            "exit_tp2_better_pct": exit_stats.get("holding_to_tp2_better_pct", 0.0),
            "insights": self.get_learning_insights()[:3],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Save scenarios to disk. Must be called with self._lock held."""
        try:
            data = {
                "version": 1,
                "updated_at": time.time(),
                "scenarios": [s.to_dict() for s in self._scenarios],
            }
            tmp_path = self._scenarios_file + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._scenarios_file)
        except Exception as e:
            logger.warning("Failed to save counterfactual scenarios: %s", e)

    def _load(self) -> None:
        """Load scenarios from disk."""
        if not os.path.exists(self._scenarios_file):
            return
        try:
            with open(self._scenarios_file, "r") as f:
                data = json.load(f)
            raw_scenarios = data.get("scenarios", [])
            self._scenarios = [
                CounterfactualScenario.from_dict(s) for s in raw_scenarios
            ]
            self._cleanup_old()
            logger.info(
                "[COUNTERFACTUAL] Loaded %d scenarios (%d pending)",
                len(self._scenarios),
                sum(1 for s in self._scenarios if not s.resolved),
            )
        except Exception as e:
            logger.warning("Failed to load counterfactual scenarios: %s", e)
            self._scenarios = []

    def _cleanup_old(self) -> None:
        """Remove old resolved scenarios to prevent unbounded growth."""
        now = time.time()
        resolved = [s for s in self._scenarios if s.resolved]

        if len(resolved) <= self.MAX_RESOLVED_SCENARIOS:
            return

        # Keep the most recent MAX_RESOLVED_SCENARIOS resolved entries
        # plus all pending ones
        resolved_sorted = sorted(resolved, key=lambda s: s.timestamp, reverse=True)
        keep_resolved = set(
            s.id for s in resolved_sorted[:self.MAX_RESOLVED_SCENARIOS]
        )

        before = len(self._scenarios)
        self._scenarios = [
            s for s in self._scenarios
            if not s.resolved or s.id in keep_resolved
        ]
        removed = before - len(self._scenarios)
        if removed > 0:
            logger.info(
                "[COUNTERFACTUAL] Cleaned up %d old resolved scenarios", removed
            )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _find_by_id(self, scenario_id: str) -> Optional[CounterfactualScenario]:
        """Find a scenario by ID. Must be called with self._lock held."""
        for s in self._scenarios:
            if s.id == scenario_id:
                return s
        return None

    @staticmethod
    def _make_id() -> str:
        """Generate a unique scenario ID."""
        return f"cf_{int(time.time())}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_engine_instance: Optional[CounterfactualEngine] = None
_engine_lock = threading.Lock()


def get_counterfactual_engine(
    data_dir: str = "data/counterfactuals",
) -> CounterfactualEngine:
    """Get or create the singleton CounterfactualEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            # Double-checked locking
            if _engine_instance is None:
                _engine_instance = CounterfactualEngine(data_dir=data_dir)
    return _engine_instance
