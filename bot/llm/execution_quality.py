"""
TIER 2.2: Execution Quality Tracking

Measures execution cost vs. expected cost to understand real profitability.

Why this matters:
- Signal confidence doesn't guarantee profit
- Slippage eats into small edge margins
- If avg slippage > expected edge, LLM decisions lose money despite good signals

Tracks:
  1. Expected entry price (from signal)
  2. Actual entry price (from execution)
  3. Slippage (difference)
  4. Expected PnL (from signal R:R)
  5. Actual PnL (from outcome)
  6. Slippage cost as % of profit

Expected impact: Identifies if LLM + mechanical combo is net profitable.
"""

import logging
import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import time

logger = logging.getLogger("bot.llm.execution_quality")


@dataclass
class ExecutionMetrics:
    """Execution quality for a single trade."""
    trade_id: str
    symbol: str
    side: str                      # BUY or SELL
    timestamp: float

    # Signal expectation
    signal_entry: float            # Price in signal
    signal_sl: float               # Stop loss in signal
    signal_tp1: float              # Take profit 1
    signal_confidence: float       # Signal's confidence %
    signal_rr_ratio: float         # Risk:reward from signal
    expected_pnl: float            # Expected PnL if signal perfect

    # Actual execution
    actual_entry: float            # What we actually filled at
    actual_exit: float             # Where we actually closed
    actual_sl_hit: Optional[float] = None  # Did SL trigger?

    # Costs
    slippage_entry_pct: float = 0.0  # Entry vs signal (%)
    slippage_exit_pct: float = 0.0   # Exit quality (%)
    fees_bps: float = 4.0            # Taker fees in bps

    # Outcomes
    actual_pnl: float = 0.0
    actual_pnl_pct: float = 0.0
    win: bool = False
    hold_time_minutes: float = 0.0

    # Analysis
    slippage_cost_vs_profit: float = 0.0  # Slippage as % of would-be profit
    expected_vs_actual: float = 0.0       # (actual - expected) / expected
    reasoning: str = ""


class ExecutionQualityTracker:
    """
    Tracks execution quality and slippage impact on profitability.

    Goal: Understand if LLM decisions are actually profitable after costs.
    """

    def __init__(self, output_dir: str = "data/llm"):
        self.output_dir = output_dir
        self.output_file = os.path.join(output_dir, "execution_quality.jsonl")
        os.makedirs(output_dir, exist_ok=True)

        # In-memory cache
        self.recent_trades: List[ExecutionMetrics] = []
        self._load_recent()

        self.stats = {
            "total_trades": 0,
            "profitable_trades": 0,
            "losing_trades": 0,
            "avg_slippage_entry_pct": 0.0,
            "avg_slippage_exit_pct": 0.0,
            "avg_actual_pnl": 0.0,
            "avg_expected_pnl": 0.0,
            "slippage_ate_profit_count": 0,  # How many trades lost due to slippage?
        }

    def _load_recent(self) -> None:
        """Load recent execution records."""
        if not os.path.exists(self.output_file):
            return

        try:
            with open(self.output_file, "r") as f:
                for line in f.readlines()[-100:]:
                    try:
                        data = json.loads(line.strip())
                        metrics = ExecutionMetrics(
                            trade_id=data["trade_id"],
                            symbol=data["symbol"],
                            side=data["side"],
                            timestamp=data["timestamp"],
                            signal_entry=data["signal_entry"],
                            signal_sl=data["signal_sl"],
                            signal_tp1=data["signal_tp1"],
                            signal_confidence=data["signal_confidence"],
                            signal_rr_ratio=data["signal_rr_ratio"],
                            expected_pnl=data["expected_pnl"],
                            actual_entry=data["actual_entry"],
                            actual_exit=data["actual_exit"],
                            actual_sl_hit=data.get("actual_sl_hit"),
                            slippage_entry_pct=data.get("slippage_entry_pct", 0.0),
                            slippage_exit_pct=data.get("slippage_exit_pct", 0.0),
                            fees_bps=data.get("fees_bps", 4.0),
                            actual_pnl=data.get("actual_pnl", 0.0),
                            actual_pnl_pct=data.get("actual_pnl_pct", 0.0),
                            win=data.get("win", False),
                            hold_time_minutes=data.get("hold_time_minutes", 0.0),
                        )
                        self.recent_trades.append(metrics)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to load execution quality records: {e}")

    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        signal_entry: float,
        signal_sl: float,
        signal_tp1: float,
        signal_confidence: float,
        actual_entry: float,
        actual_exit: float,
        actual_pnl: float,
        hold_time_minutes: float = 0.0,
    ) -> ExecutionMetrics:
        """
        Record execution metrics for a closed trade.

        Args:
            trade_id: Unique trade identifier
            symbol: Trading pair
            side: BUY or SELL
            signal_entry: Entry price from signal
            signal_sl: Stop loss from signal
            signal_tp1: TP1 from signal
            signal_confidence: Signal's confidence %
            actual_entry: Where we actually entered
            actual_exit: Where we actually exited
            actual_pnl: Actual profit/loss
            hold_time_minutes: How long we held

        Returns:
            ExecutionMetrics with analysis
        """
        now = time.time()

        # Calculate expected outcome
        stop_width = abs(signal_entry - signal_sl)
        risk = stop_width
        reward = abs(signal_tp1 - signal_entry)
        rr_ratio = reward / risk if risk > 0 else 0
        expected_pnl = reward * 0.6  # Assume 60% hit TP1

        # Calculate slippage
        entry_slippage = abs(actual_entry - signal_entry) / signal_entry * 100
        exit_slippage = abs(actual_exit - signal_tp1) / signal_tp1 * 100 if signal_tp1 > 0 else 0

        # Fee cost
        fee_cost = (signal_entry * 0.0004) + (actual_exit * 0.0004)  # 4 bps round trip

        # Analyze slippage impact
        actual_pnl_pct = (actual_pnl / signal_entry) * 100 if signal_entry > 0 else 0
        slippage_cost = entry_slippage + exit_slippage

        # Did slippage eat the profit?
        would_be_profit = expected_pnl
        slippage_ate_profit = slippage_cost > would_be_profit if would_be_profit > 0 else False

        metrics = ExecutionMetrics(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            timestamp=now,
            signal_entry=signal_entry,
            signal_sl=signal_sl,
            signal_tp1=signal_tp1,
            signal_confidence=signal_confidence,
            signal_rr_ratio=rr_ratio,
            expected_pnl=expected_pnl,
            actual_entry=actual_entry,
            actual_exit=actual_exit,
            slippage_entry_pct=entry_slippage,
            slippage_exit_pct=exit_slippage,
            actual_pnl=actual_pnl,
            actual_pnl_pct=actual_pnl_pct,
            win=actual_pnl > 0,
            hold_time_minutes=hold_time_minutes,
        )

        # Analysis
        if expected_pnl > 0:
            metrics.slippage_cost_vs_profit = (slippage_cost / expected_pnl) * 100

        if expected_pnl != 0:
            metrics.expected_vs_actual = ((actual_pnl - expected_pnl) / abs(expected_pnl))

        if slippage_ate_profit:
            metrics.reasoning = f"Slippage ({slippage_cost:.2f}%) exceeded expected profit ({would_be_profit:.2f}%)"
        else:
            metrics.reasoning = f"Slippage: {slippage_cost:.2f}%, Expected: {expected_pnl:.2f}, Actual: {actual_pnl:.2f}"

        # Store
        self.recent_trades.append(metrics)
        if len(self.recent_trades) > 1000:
            self.recent_trades = self.recent_trades[-1000:]

        # Save
        try:
            with open(self.output_file, "a") as f:
                f.write(json.dumps(asdict(metrics)) + "\n")
        except Exception as e:
            logger.error(f"Failed to save execution quality: {e}")

        # Update stats
        self._update_stats()

        return metrics

    def _update_stats(self) -> None:
        """Update aggregate statistics."""
        if not self.recent_trades:
            return

        recent = self.recent_trades[-100:]  # Last 100 trades

        self.stats["total_trades"] = len(recent)
        self.stats["profitable_trades"] = sum(1 for t in recent if t.win)
        self.stats["losing_trades"] = len(recent) - self.stats["profitable_trades"]
        self.stats["avg_slippage_entry_pct"] = sum(t.slippage_entry_pct for t in recent) / len(recent) if recent else 0
        self.stats["avg_slippage_exit_pct"] = sum(t.slippage_exit_pct for t in recent) / len(recent) if recent else 0
        self.stats["avg_actual_pnl"] = sum(t.actual_pnl for t in recent) / len(recent) if recent else 0
        self.stats["avg_expected_pnl"] = sum(t.expected_pnl for t in recent) / len(recent) if recent else 0
        self.stats["slippage_ate_profit_count"] = sum(1 for t in recent if t.slippage_cost_vs_profit > 100)

    def get_profitability_analysis(self) -> Dict[str, Any]:
        """
        Get profitability breakdown: signals vs execution.

        Returns:
            Analysis showing where profit/loss comes from.
        """
        if not self.recent_trades:
            return {"status": "no_data"}

        recent = self.recent_trades[-100:]

        # Breakdown
        total_expected = sum(t.expected_pnl for t in recent)
        total_actual = sum(t.actual_pnl for t in recent)
        slippage_cost = total_expected - total_actual

        win_rate = len([t for t in recent if t.win]) / len(recent) if recent else 0

        return {
            "trades_analyzed": len(recent),
            "win_rate": f"{win_rate:.1%}",
            "expected_pnl_total": f"${total_expected:+.2f}",
            "actual_pnl_total": f"${total_actual:+.2f}",
            "slippage_cost_total": f"${slippage_cost:+.2f}",
            "slippage_as_pct_of_expected": f"{(slippage_cost / total_expected * 100) if total_expected > 0 else 0:.1f}%",
            "avg_entry_slippage": f"{self.stats['avg_slippage_entry_pct']:.3f}%",
            "avg_exit_slippage": f"{self.stats['avg_slippage_exit_pct']:.3f}%",
            "trades_where_slippage_ate_profit": self.stats["slippage_ate_profit_count"],
            "verdict": self._get_verdict(total_expected, total_actual, slippage_cost),
        }

    def _get_verdict(self, expected: float, actual: float, slippage: float) -> str:
        """Determine if execution is good or bad."""
        if expected <= 0:
            return "Not enough data"

        slippage_pct = (slippage / expected) * 100

        if slippage_pct < 10:
            return "✅ Excellent execution - slippage minimal"
        elif slippage_pct < 30:
            return "✓ Good execution - slippage acceptable"
        elif slippage_pct < 50:
            return "⚠️ Fair execution - slippage eats some profit"
        elif slippage_pct < 100:
            return "❌ Poor execution - slippage eats most profit"
        else:
            return "🔴 CRITICAL - slippage exceeded expected profit"

    def get_stats(self) -> Dict[str, Any]:
        """Get execution quality statistics."""
        return {
            "recent_100_trades": {
                "total": self.stats["total_trades"],
                "wins": self.stats["profitable_trades"],
                "losses": self.stats["losing_trades"],
                "win_rate": f"{self.stats['profitable_trades'] / max(1, self.stats['total_trades']):.1%}",
            },
            "slippage_metrics": {
                "avg_entry_slippage_pct": f"{self.stats['avg_slippage_entry_pct']:.3f}%",
                "avg_exit_slippage_pct": f"{self.stats['avg_slippage_exit_pct']:.3f}%",
                "trades_slippage_ate_profit": self.stats["slippage_ate_profit_count"],
            },
            "pnl_comparison": {
                "avg_expected_pnl": f"${self.stats['avg_expected_pnl']:+.2f}",
                "avg_actual_pnl": f"${self.stats['avg_actual_pnl']:+.2f}",
                "difference": f"${self.stats['avg_expected_pnl'] - self.stats['avg_actual_pnl']:+.2f}",
            },
        }


# Global tracker
_global_tracker: Optional[ExecutionQualityTracker] = None


def get_execution_quality_tracker() -> ExecutionQualityTracker:
    """Get or create global tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = ExecutionQualityTracker()
    return _global_tracker
