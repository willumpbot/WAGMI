"""
TIER 4.6: Mechanical Bot Analysis Report

Generates comprehensive reports on mechanical bot behavior, edges, and gaps.

Reports generated:
1. Signal Report - Overall signal metrics
2. Edge Report - Genuine alpha sources identified
3. Gap Report - Market opportunities being missed
4. Regime Report - Performance by regime
5. Time Report - Performance by hour of day
6. Failure Report - Failure mode analysis
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

from mechanical_bot_memory import get_mechanical_bot_memory
from mechanical_bot_analyzer import get_mechanical_bot_analyzer
from mechanical_bot_state_tracker import get_mechanical_bot_state_tracker

logger = logging.getLogger("bot.llm.mechanical_bot_report")


class MechanicalBotReportGenerator:
    """
    Generates comprehensive reports on mechanical bot behavior.
    """

    def __init__(self):
        self.memory = get_mechanical_bot_memory()
        self.analyzer = get_mechanical_bot_analyzer()
        self.state_tracker = get_mechanical_bot_state_tracker()

    def generate_signal_report(self) -> Dict[str, Any]:
        """Generate signal metrics report."""
        stats = self.memory.stats

        return {
            "report_type": "SIGNAL_METRICS",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_signals_generated": stats["total_signals"],
                "signals_executed": stats["signals_executed"],
                "execution_rate": f"{stats['execution_rate']:.1%}",
                "total_trades": stats["signals_executed"],
                "wins": stats["total_wins"],
                "losses": stats["total_losses"],
                "win_rate": f"{stats['win_rate']:.1%}",
                "total_pnl": f"${stats['total_pnl']:.2f}",
            },
            "interpretation": self._interpret_signal_metrics(stats),
        }

    def generate_edge_report(self) -> Dict[str, Any]:
        """Generate mechanical bot edge report."""
        edges = self.analyzer.identify_mechanical_bot_edges(top_n=10)

        edge_list = []
        for edge in edges:
            edge_list.append({
                "edge_id": edge.edge_name,
                "condition": edge.condition,
                "win_rate": f"{edge.win_rate:.1%}",
                "sample_size": edge.sample_size,
                "total_pnl": f"${edge.total_pnl:.2f}",
                "consistency": f"{edge.consistency_score:.1%}",
                "time_dependent": edge.is_time_dependent,
                "reliability": "high" if edge.consistency_score > 0.75 else "medium" if edge.consistency_score > 0.60 else "low",
            })

        return {
            "report_type": "MECHANICAL_BOT_EDGES",
            "timestamp": datetime.now().isoformat(),
            "top_edges": edge_list,
            "key_insights": self._generate_edge_insights(edges),
        }

    def generate_gap_report(self) -> Dict[str, Any]:
        """Generate gaps report."""
        gaps = self.analyzer.identify_gaps(top_n=10)

        gap_list = []
        for gap in gaps:
            gap_list.append({
                "gap_id": gap.gap_id,
                "description": gap.description,
                "condition": gap.condition,
                "expected_frequency": gap.expected_frequency,
                "estimated_pnl_opportunity": f"${gap.potential_pnl:.2f}",
                "confidence": f"{gap.confidence_in_estimate:.0%}",
                "suggested_setup": gap.suggested_setup,
                "similarity_to_bot": f"{gap.similarity_to_bot_patterns:.0%}",
            })

        return {
            "report_type": "TRADING_GAPS",
            "timestamp": datetime.now().isoformat(),
            "identified_gaps": gap_list,
            "gap_opportunities": self._generate_gap_opportunities(gaps),
        }

    def generate_regime_report(self) -> Dict[str, Any]:
        """Generate regime performance report."""
        regime_perf = self.analyzer.get_regime_performance()

        regime_list = []
        for regime, perf in regime_perf.items():
            regime_list.append({
                "regime": regime,
                "trades": perf["count"],
                "win_rate": f"{perf['win_rate']:.1%}",
                "wins": perf["wins"],
                "losses": perf["losses"],
                "total_pnl": f"${perf['total_pnl']:.2f}",
                "avg_pnl": f"${perf['avg_pnl']:.2f}",
                "avg_confidence": f"{perf['avg_confidence']:.0f}%",
                "recommendation": self._regime_recommendation(perf["win_rate"]),
            })

        # Sort by trade count descending
        regime_list.sort(key=lambda x: x["trades"], reverse=True)

        return {
            "report_type": "REGIME_PERFORMANCE",
            "timestamp": datetime.now().isoformat(),
            "regime_analysis": regime_list,
            "best_regime": max(regime_list, key=lambda x: float(x["win_rate"].strip("%")) / 100) if regime_list else None,
            "worst_regime": min(regime_list, key=lambda x: float(x["win_rate"].strip("%")) / 100) if regime_list else None,
        }

    def generate_time_report(self) -> Dict[str, Any]:
        """Generate time-of-day performance report."""
        time_perf = self.analyzer.get_time_of_day_performance()

        hour_list = []
        for hour in sorted(time_perf.keys()):
            perf = time_perf[hour]
            hour_period = (
                "Asia" if 0 <= hour < 8
                else "Europe" if 8 <= hour < 16
                else "US" if 14 <= hour < 22
                else "Off-Hours"
            )

            hour_list.append({
                "hour": f"{hour:02d}:00",
                "period": hour_period,
                "trades": perf["count"],
                "win_rate": f"{perf['win_rate']:.1%}",
                "total_pnl": f"${perf['total_pnl']:.2f}",
                "avg_confidence": f"{perf['avg_confidence']:.0f}%",
            })

        return {
            "report_type": "TIME_OF_DAY_ANALYSIS",
            "timestamp": datetime.now().isoformat(),
            "hourly_breakdown": hour_list,
            "peak_trading_hours": self._find_peak_hours(hour_list),
        }

    def generate_failure_report(self) -> Dict[str, Any]:
        """Generate failure analysis report."""
        failures = self.analyzer.get_failure_analysis()

        failure_list = []
        for failure_mode, count in failures:
            failure_list.append({
                "failure_mode": failure_mode,
                "occurrences": count,
                "percentage": f"{count / sum(c for _, c in failures) * 100:.1f}%",
            })

        # Get actual failure records for detailed analysis
        failure_records = self.memory.get_failures()

        most_expensive_losses = sorted(
            failure_records,
            key=lambda f: f.signal.pnl if f.signal.pnl else 0
        )[:5]

        return {
            "report_type": "FAILURE_ANALYSIS",
            "timestamp": datetime.now().isoformat(),
            "failure_modes": failure_list,
            "total_failures": len(failure_records),
            "avg_loss_per_failure": f"${sum(f.signal.pnl for f in failure_records if f.signal.pnl) / len(failure_records):.2f}" if failure_records else "N/A",
            "prevention_insights": self._generate_prevention_insights(failures),
        }

    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate complete report with all sections."""
        return {
            "report_timestamp": datetime.now().isoformat(),
            "report_type": "COMPREHENSIVE_BOT_ANALYSIS",
            "signal_metrics": self.generate_signal_report(),
            "mechanical_edges": self.generate_edge_report(),
            "trading_gaps": self.generate_gap_report(),
            "regime_analysis": self.generate_regime_report(),
            "time_analysis": self.generate_time_report(),
            "failure_analysis": self.generate_failure_report(),
            "executive_summary": self._generate_executive_summary(),
        }

    def save_report(self, report: Dict, filename: str = None) -> str:
        """Save report to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/llm/reports/mechanical_bot_report_{timestamp}.json"

        try:
            import os
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"Report saved to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
            return ""

    def print_report_summary(self, report: Dict = None) -> str:
        """Print human-readable report summary."""
        if report is None:
            report = self.generate_comprehensive_report()

        output = []
        output.append("\n" + "=" * 80)
        output.append("MECHANICAL BOT COMPREHENSIVE ANALYSIS REPORT")
        output.append("=" * 80)

        # Signal metrics
        sig = report["signal_metrics"]["summary"]
        output.append(f"\n📊 SIGNAL METRICS")
        output.append(f"  • Generated: {sig['total_signals_generated']}")
        output.append(f"  • Executed: {sig['signals_executed']} ({sig['execution_rate']})")
        output.append(f"  • Win Rate: {sig['win_rate']} ({sig['wins']}W / {sig['losses']}L)")
        output.append(f"  • Total PnL: {sig['total_pnl']}")

        # Edges
        edges = report["mechanical_edges"]["top_edges"]
        if edges:
            output.append(f"\n🎯 TOP MECHANICAL EDGES")
            for edge in edges[:3]:
                output.append(f"  • {edge['condition']}")
                output.append(f"    Win Rate: {edge['win_rate']}, Samples: {edge['sample_size']}, PnL: {edge['total_pnl']}")

        # Gaps
        gaps = report["trading_gaps"]["identified_gaps"]
        if gaps:
            output.append(f"\n⚠️  IDENTIFIED TRADING GAPS")
            for gap in gaps[:3]:
                output.append(f"  • {gap['description']}")
                output.append(f"    Frequency: {gap['expected_frequency']}, Est. Opportunity: {gap['estimated_pnl_opportunity']}")

        # Regime analysis
        regimes = report["regime_analysis"]["regime_analysis"]
        output.append(f"\n📈 REGIME PERFORMANCE")
        for regime in regimes[:5]:
            output.append(f"  • {regime['regime']}: {regime['win_rate']} WR ({regime['wins']}W/{regime['losses']}L), PnL: {regime['total_pnl']}")

        # Recommendations
        if "executive_summary" in report and "recommendations" in report["executive_summary"]:
            output.append(f"\n💡 RECOMMENDATIONS")
            for rec in report["executive_summary"]["recommendations"][:5]:
                output.append(f"  • {rec}")

        output.append("\n" + "=" * 80)

        return "\n".join(output)

    # Helper methods
    def _interpret_signal_metrics(self, stats: Dict) -> List[str]:
        """Interpret signal metrics."""
        insights = []

        if stats["execution_rate"] < 0.05:
            insights.append("Very low execution rate - mechanical system is highly selective")
        elif stats["execution_rate"] > 0.5:
            insights.append("High execution rate - mechanical system generates frequent signals")

        if stats["win_rate"] > 0.60:
            insights.append("Strong win rate indicates high signal quality")
        elif stats["win_rate"] < 0.40:
            insights.append("Low win rate - focus on filtering low-quality signals")

        return insights

    def _generate_edge_insights(self, edges: List) -> List[str]:
        """Generate insights about mechanical bot edges."""
        insights = []

        if edges:
            strongest_edge = edges[0]
            insights.append(f"Strongest edge: {strongest_edge.edge_name} with {strongest_edge.win_rate:.0%} win rate")

        time_dependent_edges = [e for e in edges if e.is_time_dependent]
        if time_dependent_edges:
            insights.append(f"{len(time_dependent_edges)} edges show time-of-day dependency")

        return insights

    def _generate_gap_opportunities(self, gaps: List) -> List[str]:
        """Generate insights about gaps."""
        opportunities = []

        for gap in gaps[:3]:
            opportunities.append(f"{gap.description} (Est. opportunity: ${gap.potential_pnl:.2f})")

        return opportunities

    def _regime_recommendation(self, win_rate: float) -> str:
        """Get recommendation for regime."""
        if win_rate > 0.60:
            return "✅ Strong - favor this regime"
        elif win_rate > 0.50:
            return "➡️  Neutral - trade normally"
        elif win_rate > 0.40:
            return "⚠️  Weak - be selective"
        else:
            return "❌ Poor - avoid if possible"

    def _find_peak_hours(self, hour_list: List[Dict]) -> List[str]:
        """Find peak trading hours."""
        if not hour_list:
            return []

        sorted_hours = sorted(
            [h for h in hour_list if h["trades"] > 0],
            key=lambda x: x["trades"],
            reverse=True
        )

        return [h["hour"] for h in sorted_hours[:3]]

    def _generate_prevention_insights(self, failures: List) -> List[str]:
        """Generate insights to prevent failures."""
        insights = []

        if failures:
            most_common = failures[0]
            if most_common[0] == "whipsaw":
                insights.append("Whipsaws are common - consider wider stops or entry filtering")
            elif most_common[0] == "black_swan":
                insights.append("Black swans occur - ensure proper position sizing")
            elif most_common[0] == "wrong_direction":
                insights.append("Wrong direction calls - validate regime classification")

        return insights

    def _generate_executive_summary(self) -> Dict[str, Any]:
        """Generate executive summary."""
        stats = self.memory.stats
        analysis = self.analyzer.get_comprehensive_analysis()

        return {
            "bot_status": "Operational" if stats["total_signals"] > 0 else "No Data",
            "overall_performance": f"{stats['win_rate']:.0%} win rate on {stats['signals_executed']} trades",
            "profitability": "Profitable" if stats["total_pnl"] > 0 else "Unprofitable" if stats["total_pnl"] < 0 else "Breakeven",
            "data_quality": f"Based on {stats['total_signals']} signals",
            "recommendations": analysis.recommendations,
        }


# Global report generator
_global_generator: Optional[MechanicalBotReportGenerator] = None


def get_mechanical_bot_report_generator() -> MechanicalBotReportGenerator:
    """Get or create global report generator."""
    global _global_generator
    if _global_generator is None:
        _global_generator = MechanicalBotReportGenerator()
    return _global_generator
