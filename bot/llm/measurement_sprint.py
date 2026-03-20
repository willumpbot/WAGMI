"""
TIER 2.5: Measurement Sprint

The truth test: Is the LLM system actually profitable?

Before deploying TIER 3 work, we need to validate that TIER 1-2 improvements
actually make money. This module tracks the financial impact of LLM decisions.

Key metrics:
  1. Cost per decision: $0.007 (6 agents) → $0.009 (with debate)
  2. Profit per decision: Avg PnL from LLM-gated signals
  3. Net ROI: (Profit - Cost) / Cost
  4. Mechanical system baseline: Avg PnL without LLM gating

Decision rules:
  ✅ Keep LLM if: Net ROI > 20% (profit per decision > $0.0016)
  ⚠️ Uncertain if: Net ROI in 5-20% (gray zone)
  ❌ Disable LLM if: Net ROI < 5% (not worth the cost)

Expected outcome:
  - Either LLM adds clear value ($0.70+/day on 100 trades)
  - Or we disable it and rely on pure mechanical system
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import time

logger = logging.getLogger("bot.llm.measurement_sprint")


@dataclass
class CostMetrics:
    """Cost tracking for LLM operations."""
    datetime: str
    total_decisions: int = 0
    total_api_calls: int = 0
    regime_agent_calls: int = 0
    trade_agent_calls: int = 0
    critic_agent_calls: int = 0
    debate_calls: int = 0

    # Cost breakdown (USD)
    total_cost: float = 0.0
    regime_cost: float = 0.0  # Haiku: $1/1M tokens
    trade_cost: float = 0.0   # Sonnet: $3/1M tokens
    critic_cost: float = 0.0  # Sonnet: $3/1M tokens
    debate_cost: float = 0.0  # Sonnet: $3/1M tokens

    # Cost per decision
    cost_per_decision: float = 0.0


@dataclass
class ProfitMetrics:
    """Profit tracking for trades."""
    datetime: str
    total_trades: int = 0
    profitable_trades: int = 0
    losing_trades: int = 0

    # PnL breakdown
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    wins_pnl: float = 0.0
    losses_pnl: float = 0.0

    # Metrics
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0  # wins_pnl / abs(losses_pnl)

    # Slippage analysis
    avg_slippage_pct: float = 0.0
    trades_slippage_ate_profit: int = 0


@dataclass
class MeasurementCycle:
    """One measurement cycle (e.g., 1 day)."""
    cycle_id: str
    datetime: str
    period: str  # "1d", "7d", "30d"

    # Cost metrics
    costs: CostMetrics = field(default_factory=CostMetrics)

    # Profit metrics (LLM-gated trades)
    llm_trades: ProfitMetrics = field(default_factory=ProfitMetrics)

    # Profit metrics (mechanical-only, no LLM gating)
    baseline_trades: ProfitMetrics = field(default_factory=ProfitMetrics)

    # ROI Analysis
    llm_pnl: float = 0.0
    baseline_pnl: float = 0.0
    llm_cost: float = 0.0
    net_roi_pct: float = 0.0  # (llm_pnl - cost) / cost

    # Recommendation
    recommendation: str = ""  # "keep" | "uncertain" | "disable"
    reasoning: str = ""


class MeasurementSprint:
    """
    Measures profitability impact of LLM system.

    Runs for 5-7 days of paper trading:
    - Day 1-3: Gather baseline (mechanical system)
    - Day 4-5: Run with LLM improvements
    - Compare results
    - Make go/no-go decision
    """

    def __init__(self, output_dir: str = "data/llm"):
        self.output_dir = output_dir
        self.output_file = os.path.join(output_dir, "measurement_sprint.jsonl")
        os.makedirs(output_dir, exist_ok=True)

        self.cycles: List[MeasurementCycle] = []
        self.current_cycle: Optional[MeasurementCycle] = None

    def start_cycle(self, period: str = "1d") -> MeasurementCycle:
        """Start a new measurement cycle."""
        cycle_id = f"{period}_{int(time.time())}"
        cycle = MeasurementCycle(
            cycle_id=cycle_id,
            datetime=datetime.now().isoformat(),
            period=period,
            costs=CostMetrics(datetime=datetime.now().isoformat()),
            llm_trades=ProfitMetrics(datetime=datetime.now().isoformat()),
            baseline_trades=ProfitMetrics(datetime=datetime.now().isoformat()),
        )
        self.current_cycle = cycle
        logger.info(f"[MEASUREMENT] Started cycle {cycle_id}")
        return cycle

    def record_llm_decision(
        self,
        cost_usd: float,
        api_calls: Dict[str, int],  # {"regime": 1, "trade": 1, "critic": 1, ...}
    ) -> None:
        """Record cost of a single LLM decision."""
        if not self.current_cycle:
            return

        self.current_cycle.costs.total_decisions += 1
        self.current_cycle.costs.total_api_calls += sum(api_calls.values())
        self.current_cycle.costs.regime_agent_calls += api_calls.get("regime", 0)
        self.current_cycle.costs.trade_agent_calls += api_calls.get("trade", 0)
        self.current_cycle.costs.critic_agent_calls += api_calls.get("critic", 0)
        self.current_cycle.costs.debate_calls += api_calls.get("debate", 0)
        self.current_cycle.costs.total_cost += cost_usd

        if self.current_cycle.costs.total_decisions > 0:
            self.current_cycle.costs.cost_per_decision = (
                self.current_cycle.costs.total_cost / self.current_cycle.costs.total_decisions
            )

    def record_llm_trade(
        self,
        pnl: float,
        is_win: bool,
    ) -> None:
        """Record outcome of a trade made with LLM gating."""
        if not self.current_cycle:
            return

        trades = self.current_cycle.llm_trades
        trades.total_trades += 1
        trades.total_pnl += pnl

        if is_win:
            trades.profitable_trades += 1
            trades.wins_pnl += pnl
        else:
            trades.losing_trades += 1
            trades.losses_pnl += pnl

        if trades.total_trades > 0:
            trades.avg_pnl_per_trade = trades.total_pnl / trades.total_trades
            trades.win_rate = trades.profitable_trades / trades.total_trades
            trades.avg_win = trades.wins_pnl / trades.profitable_trades if trades.profitable_trades > 0 else 0
            trades.avg_loss = trades.losses_pnl / trades.losing_trades if trades.losing_trades > 0 else 0

            if abs(trades.losses_pnl) > 0:
                trades.profit_factor = trades.wins_pnl / abs(trades.losses_pnl)

    def record_baseline_trade(
        self,
        pnl: float,
        is_win: bool,
    ) -> None:
        """Record outcome of trade WITHOUT LLM gating (baseline)."""
        if not self.current_cycle:
            return

        trades = self.current_cycle.baseline_trades
        trades.total_trades += 1
        trades.total_pnl += pnl

        if is_win:
            trades.profitable_trades += 1
            trades.wins_pnl += pnl
        else:
            trades.losing_trades += 1
            trades.losses_pnl += pnl

        if trades.total_trades > 0:
            trades.avg_pnl_per_trade = trades.total_pnl / trades.total_trades
            trades.win_rate = trades.profitable_trades / trades.total_trades
            trades.avg_win = trades.wins_pnl / trades.profitable_trades if trades.profitable_trades > 0 else 0
            trades.avg_loss = trades.losses_pnl / trades.losing_trades if trades.losing_trades > 0 else 0

            if abs(trades.losses_pnl) > 0:
                trades.profit_factor = trades.wins_pnl / abs(trades.losses_pnl)

    def end_cycle(self) -> MeasurementCycle:
        """Complete current cycle and generate recommendation."""
        if not self.current_cycle:
            return None

        cycle = self.current_cycle

        # Calculate ROI
        cycle.llm_pnl = cycle.llm_trades.total_pnl
        cycle.baseline_pnl = cycle.baseline_trades.total_pnl
        cycle.llm_cost = cycle.costs.total_cost

        # Net ROI: (LLM profit - cost) compared to baseline
        if cycle.llm_cost > 0:
            net_profit = cycle.llm_pnl - cycle.llm_cost
            cycle.net_roi_pct = (net_profit / cycle.llm_cost) * 100
        else:
            cycle.net_roi_pct = 0

        # Recommendation logic
        if cycle.net_roi_pct > 20:
            cycle.recommendation = "keep"
            cycle.reasoning = f"✅ Strong ROI: {cycle.net_roi_pct:.0f}% gain after costs. LLM adds {cycle.llm_pnl - cycle.baseline_pnl:+.2f} vs baseline."
        elif cycle.net_roi_pct > 5:
            cycle.recommendation = "uncertain"
            cycle.reasoning = f"⚠️ Marginal ROI: {cycle.net_roi_pct:.0f}% gain. Gray zone - run longer test."
        else:
            cycle.recommendation = "disable"
            cycle.reasoning = f"❌ Poor ROI: {cycle.net_roi_pct:.0f}% gain insufficient. Disable LLM, use mechanical only."

        # Save cycle
        self.cycles.append(cycle)
        self._save_cycle(cycle)

        logger.info(f"[MEASUREMENT] Cycle {cycle.cycle_id} complete: {cycle.recommendation} ({cycle.net_roi_pct:.0f}% ROI)")

        self.current_cycle = None
        return cycle

    def _save_cycle(self, cycle: MeasurementCycle) -> None:
        """Save cycle to disk."""
        try:
            with open(self.output_file, "a") as f:
                f.write(json.dumps(self._cycle_to_dict(cycle)) + "\n")
        except Exception as e:
            logger.error(f"Failed to save measurement cycle: {e}")

    def _cycle_to_dict(self, cycle: MeasurementCycle) -> Dict:
        """Convert cycle to dict for JSON."""
        return {
            "cycle_id": cycle.cycle_id,
            "datetime": cycle.datetime,
            "period": cycle.period,
            "llm_metrics": {
                "trades": cycle.llm_trades.total_trades,
                "win_rate": f"{cycle.llm_trades.win_rate:.0%}",
                "total_pnl": f"${cycle.llm_trades.total_pnl:+.2f}",
                "profit_factor": f"{cycle.llm_trades.profit_factor:.2f}",
            },
            "baseline_metrics": {
                "trades": cycle.baseline_trades.total_trades,
                "win_rate": f"{cycle.baseline_trades.win_rate:.0%}",
                "total_pnl": f"${cycle.baseline_trades.total_pnl:+.2f}",
                "profit_factor": f"{cycle.baseline_trades.profit_factor:.2f}",
            },
            "costs": {
                "total_decisions": cycle.costs.total_decisions,
                "total_cost_usd": f"${cycle.costs.total_cost:.4f}",
                "cost_per_decision": f"${cycle.costs.cost_per_decision:.4f}",
            },
            "roi_analysis": {
                "llm_pnl": f"${cycle.llm_pnl:+.2f}",
                "llm_cost": f"${cycle.llm_cost:.4f}",
                "net_roi_pct": f"{cycle.net_roi_pct:.1f}%",
            },
            "recommendation": cycle.recommendation,
            "reasoning": cycle.reasoning,
        }

    def get_summary_report(self) -> Dict[str, Any]:
        """Get summary report of all cycles."""
        if not self.cycles:
            return {"status": "no_data"}

        keep_count = sum(1 for c in self.cycles if c.recommendation == "keep")
        uncertain_count = sum(1 for c in self.cycles if c.recommendation == "uncertain")
        disable_count = sum(1 for c in self.cycles if c.recommendation == "disable")

        total_llm_pnl = sum(c.llm_pnl for c in self.cycles)
        total_cost = sum(c.llm_cost for c in self.cycles)
        total_baseline = sum(c.baseline_pnl for c in self.cycles)

        return {
            "total_cycles": len(self.cycles),
            "recommendation_summary": {
                "keep": keep_count,
                "uncertain": uncertain_count,
                "disable": disable_count,
            },
            "financial_summary": {
                "total_llm_pnl": f"${total_llm_pnl:+.2f}",
                "total_baseline_pnl": f"${total_baseline:+.2f}",
                "llm_vs_baseline": f"${total_llm_pnl - total_baseline:+.2f}",
                "total_llm_cost": f"${total_cost:.4f}",
                "net_profit": f"${total_llm_pnl - total_cost:+.2f}",
            },
            "overall_verdict": self._get_overall_verdict(),
        }

    def _get_overall_verdict(self) -> str:
        """Get overall verdict based on cycles."""
        if not self.cycles:
            return "No data"

        keep_count = sum(1 for c in self.cycles if c.recommendation == "keep")
        disable_count = sum(1 for c in self.cycles if c.recommendation == "disable")

        if keep_count >= 2:
            return "✅ KEEP LLM - Multiple cycles show positive ROI"
        elif disable_count >= 2:
            return "❌ DISABLE LLM - Multiple cycles show negative ROI"
        else:
            return "⚠️ UNCERTAIN - Mixed results, run longer test"


# Global measurement sprint
_global_sprint: Optional[MeasurementSprint] = None


def get_measurement_sprint() -> MeasurementSprint:
    """Get or create global measurement sprint."""
    global _global_sprint
    if _global_sprint is None:
        _global_sprint = MeasurementSprint()
    return _global_sprint
