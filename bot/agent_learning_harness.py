"""
Agent Learning Harness

Orchestrates Claude agents to analyze backtest data and build understanding
of system wiring, signal generation, chart patterns, market conditions.

Agents get FULL CONTEXT:
- All signals (won/lost) across all conditions
- Regime classification and market structure
- Setup types and strategy performance
- Historical patterns and what worked when
- Complete system architecture

Agents BUILD:
- Confidence calibration curves
- Regime understanding (why ranging fails, trending succeeds)
- Setup quality models
- Symbol-specific edges
- Time-of-day patterns
- Chart pattern recognition
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentLearningHarness:
    """Orchestrates agent learning from backtest data."""

    def __init__(self):
        self.bot_dir = Path(".")
        self.data_dir = self.bot_dir / "data"

    def prepare_agent_context(self, signal_data: Dict[str, Any], backtest_output: str) -> str:
        """Prepare comprehensive context for agents to learn from."""

        context = f"""
BACKTEST DATA FOR AGENT LEARNING
================================

SIGNAL GENERATION:
- Total signals generated: {signal_data.get('signals_generated', 0)}
- Total signals executed: {signal_data.get('signals_executed', 0)}
- Conversion rate: {(signal_data.get('signals_executed', 0) / max(1, signal_data.get('signals_generated', 0)) * 100):.2f}%
- Overall win rate: {signal_data.get('win_rate', 0):.1f}%

BY REGIME (Which market conditions worked best?):
"""
        for regime, stats in signal_data.get("by_regime", {}).items():
            context += f"\n  {regime}:"
            context += f"\n    - Trades: {stats.get('trades', 0)}"
            context += f"\n    - Win Rate: {stats.get('wr', 0):.1f}%"
            context += f"\n    - Quality: {'Good' if stats.get('wr', 0) > 50 else 'Poor'}"

        context += "\n\nBY SETUP TYPE (Which setups are profitable?):\n"
        for setup, stats in signal_data.get("by_setup", {}).items():
            context += f"\n  {setup}:"
            context += f"\n    - Trades: {stats.get('trades', 0)}"
            context += f"\n    - Win Rate: {stats.get('wr', 0):.1f}%"
            context += f"\n    - Quality: {'Good' if stats.get('wr', 0) > 50 else 'Poor'}"

        context += "\n\nSYSTEM ARCHITECTURE:\n"
        context += """
The system generates signals through:
1. Regime Agent: Classifies market state (trending/ranging/consolidation/volatile)
2. Trade Agent: Forms directional thesis based on regime and strategy signals
3. Risk Agent: Sizes positions based on confidence and leverage rules
4. Critic Agent: Stress-tests thesis, provides counter-arguments
5. Learning Agent: Extracts lessons from closed trades
6. Exit Agent: Monitors open positions, reassesses thesis

Strategies voting in ensemble:
- bollinger_squeeze: Volatility contraction + breakout
- regime_trend: Trend following with regime confirmation
- multi_tier_quality: Multi-timeframe signal quality
- monte_carlo_zones: Support/resistance zone trading
- confidence_scorer: Multi-factor confidence scoring

Each strategy outputs: side (BUY/SELL), confidence (0-100), entry/SL/TP levels
Ensemble votes on which signals pass through to execution

SIGNAL QUALITY FACTORS:
- Confidence level (agent belief in trade)
- Strategy agreement (solo vs consensus)
- Market regime (trending better than ranging)
- Setup type (trend_follow > mean_reversion)
- Recent performance (hot streak vs cold streak)
- Time of day (certain hours more profitable)
- Symbol edge (some symbols have better WR)
"""

        context += "\n\nFULL BACKTEST OUTPUT FOR PATTERN ANALYSIS:\n"
        context += backtest_output[-5000:]  # Last 5000 chars of output

        return context

    def run_agent_learning(self, context: str) -> Dict[str, Any]:
        """Run Claude agent learning analysis via CLI."""

        logger.info("Invoking agents for deep learning analysis...")

        prompt = f"""
You are a quantitative trading analyst with access to complete backtest data.
Analyze this data to extract deep understanding of our system.

{context}

ANALYSIS REQUIRED:

1. REGIME UNDERSTANDING
   - Which regimes are truly profitable? Why?
   - What market conditions matter most?
   - How can we predict regime shifts?

2. SETUP QUALITY ANALYSIS
   - Which setups work in which regimes?
   - Are mean_reversion truly unprofitable, or just in certain conditions?
   - What makes a "good" setup vs "bad" setup?

3. SIGNAL GENERATION PATTERNS
   - How does our ensemble voting work in practice?
   - When does solo signal outperform consensus?
   - What confidence levels actually predict wins?

4. SYSTEM WIRING INSIGHTS
   - How do regime + setup + strategy interact?
   - What's the causal chain: regime → setup quality → trade outcome?
   - Where can we add most value with agent coaching?

5. EDGE DISCOVERY
   - What edges exist in the data?
   - By symbol? By time? By regime? By setup?
   - How many trades needed to validate each edge?

6. AGENT COACHING OPPORTUNITIES
   - Where should we focus agent effort?
   - What decisions matter most?
   - How can agents improve on mechanical baseline?

Provide structured analysis with specific numbers, thresholds, and actionable insights.
"""

        # Call Claude via CLI
        cmd = [
            "claude",
            "--print",
            "--output-format", "json",
            prompt
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                try:
                    output = json.loads(result.stdout)
                    logger.info("Agent learning analysis complete")
                    return {
                        "success": True,
                        "analysis": output
                    }
                except json.JSONDecodeError:
                    logger.warning("Could not parse agent output as JSON")
                    return {
                        "success": True,
                        "analysis": result.stdout
                    }
            else:
                logger.error(f"Agent call failed: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr
                }

        except subprocess.TimeoutExpired:
            logger.error("Agent learning analysis timed out")
            return {
                "success": False,
                "error": "timeout"
            }

    def save_learning_insights(self, cycle_id: str, insights: Dict[str, Any]):
        """Save agent learning insights for future reference."""

        insights_file = self.data_dir / f"agent_learning_{cycle_id}.json"
        with open(insights_file, 'w') as f:
            json.dump(insights, f, indent=2)

        logger.info(f"Learning insights saved: {insights_file}")

    def build_agent_knowledge(self, cycles_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build consolidated knowledge from multiple learning cycles."""

        knowledge = {
            "regime_patterns": {},
            "setup_patterns": {},
            "confidence_calibration": {},
            "symbol_edges": {},
            "temporal_patterns": {},
            "system_understanding": {},
            "agent_coaching_guide": {}
        }

        # Consolidate patterns across cycles
        for cycle in cycles_data:
            signal_data = cycle.get("signal_data", {})

            # Accumulate regime understanding
            for regime, stats in signal_data.get("by_regime", {}).items():
                if regime not in knowledge["regime_patterns"]:
                    knowledge["regime_patterns"][regime] = []
                knowledge["regime_patterns"][regime].append(stats)

            # Accumulate setup understanding
            for setup, stats in signal_data.get("by_setup", {}).items():
                if setup not in knowledge["setup_patterns"]:
                    knowledge["setup_patterns"][setup] = []
                knowledge["setup_patterns"][setup].append(stats)

        # Compute aggregate statistics
        for regime, observations in knowledge["regime_patterns"].items():
            wrs = [o.get("wr", 0) for o in observations]
            knowledge["regime_patterns"][regime] = {
                "observations": len(observations),
                "avg_wr": sum(wrs) / len(wrs) if wrs else 0,
                "min_wr": min(wrs) if wrs else 0,
                "max_wr": max(wrs) if wrs else 0,
                "volatility": max(wrs) - min(wrs) if wrs else 0,
                "recommendation": "prioritize" if (sum(wrs) / len(wrs)) > 50 else "investigate"
            }

        return knowledge

    def run_agent_learning_cycle(self, cycle_id: str, backtest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run complete agent learning cycle on backtest data."""

        logger.info(f"\n{'='*60}")
        logger.info(f"AGENT LEARNING CYCLE: {cycle_id}")
        logger.info(f"{'='*60}\n")

        # Prepare context
        signal_data = backtest_data.get("signal_data", {})
        backtest_output = backtest_data.get("metrics", {}).get("raw_output", "")

        context = self.prepare_agent_context(signal_data, backtest_output)

        # Run agent learning
        agent_output = self.run_agent_learning(context)

        # Save insights
        if agent_output.get("success"):
            self.save_learning_insights(cycle_id, agent_output["analysis"])

        return {
            "cycle_id": cycle_id,
            "signal_data": signal_data,
            "agent_analysis": agent_output,
            "success": agent_output.get("success", False)
        }


if __name__ == "__main__":
    # Example: Run agent learning on recent backtest
    harness = AgentLearningHarness()

    # Load most recent backtest data
    data_dir = harness.data_dir / "backtest_results"
    if data_dir.exists():
        latest_backtest = sorted(data_dir.glob("*.json"))[-1]
        with open(latest_backtest) as f:
            backtest_data = json.load(f)

        # Run learning cycle
        result = harness.run_agent_learning_cycle(
            cycle_id=latest_backtest.stem,
            backtest_data=backtest_data
        )

        logger.info(f"Learning cycle complete: {result['success']}")
