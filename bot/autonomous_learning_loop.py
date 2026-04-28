"""
Autonomous Agent Learning Loop

Runs continuous backtests and extracts data for agents to learn from.
Agents build understanding of system wiring, signal generation, patterns.
Repeats autonomously to accumulate knowledge over years of data.

Architecture:
1. Run full backtest (year+ of data)
2. Extract all signals + outcomes + regimes + setups
3. Agents analyze patterns (by regime, setup, symbol, hour, confidence)
4. Build knowledge: confidence calibration, regime understanding, setup quality
5. Update memory systems
6. Repeat on new data window
7. Compound learning over time
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AutonomousLearningLoop:
    """Runs continuous backtests and agent learning cycles."""

    def __init__(self, bot_dir: str = "."):
        self.bot_dir = Path(bot_dir)
        self.data_dir = self.bot_dir / "data"
        self.decisions_file = self.data_dir / "decisions.jsonl"
        self.backtest_results = self.data_dir / "backtest_results"
        self.backtest_results.mkdir(exist_ok=True)

    def run_backtest(self, symbols: List[str], days: int, run_id: str) -> Dict[str, Any]:
        """Run backtest and return metrics."""
        import subprocess

        logger.info(f"[RUN {run_id}] Starting backtest: {symbols}, {days} days")

        cmd = [
            "python", "run.py", "backtest",
            "--symbols", ",".join(symbols),
            "--days", str(days)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.bot_dir)

        if result.returncode != 0:
            logger.error(f"Backtest failed: {result.stderr}")
            return None

        # Parse output for key metrics
        output = result.stdout
        metrics = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "symbols": symbols,
            "days": days,
            "raw_output": output
        }

        logger.info(f"[RUN {run_id}] Backtest completed")
        return metrics

    def extract_signal_data(self, output: str) -> Dict[str, Any]:
        """Extract all signals, outcomes, regimes from backtest output."""

        # Parse backtest report
        data = {
            "signals_generated": None,
            "signals_executed": None,
            "win_rate": None,
            "by_regime": {},
            "by_setup": {},
            "by_symbol": {},
            "by_hour": {},
            "confidence_buckets": {},
            "strategy_health": {}
        }

        # Extract from output (pattern matching)
        import re

        # Signals
        if match := re.search(r"Signal gen:\s+(\d+)", output):
            data["signals_generated"] = int(match.group(1))
        if match := re.search(r"Executed:\s+(\d+)", output):
            data["signals_executed"] = int(match.group(1))
        if match := re.search(r"Win Rate.*?(\d+\.\d+)%", output):
            data["win_rate"] = float(match.group(1))

        # Parse regime breakdown
        regime_section = re.search(
            r"── BY REGIME .*?\n(.*?)(?=──|\Z)",
            output,
            re.DOTALL
        )
        if regime_section:
            for line in regime_section.group(1).split('\n'):
                if match := re.search(r"(\w+(?:_\w+)*)\s+(\d+)\s+trades.*?WR=\s+([\d.]+)%", line):
                    regime, count, wr = match.groups()
                    data["by_regime"][regime] = {"trades": int(count), "wr": float(wr)}

        # Parse setup breakdown
        setup_section = re.search(
            r"── BY SETUP TYPE .*?\n(.*?)(?=──|\Z)",
            output,
            re.DOTALL
        )
        if setup_section:
            for line in setup_section.group(1).split('\n'):
                if match := re.search(r"(\w+(?:_\w+)*)\s+(\d+)\s+trades.*?WR=\s+([\d.]+)%", line):
                    setup, count, wr = match.groups()
                    data["by_setup"][setup] = {"trades": int(count), "wr": float(wr)}

        return data

    def agent_analyze_patterns(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Have agents analyze extracted signal data to build understanding."""

        insights = {
            "regime_understanding": {},
            "setup_understanding": {},
            "confidence_calibration": {},
            "signal_quality_factors": [],
            "learning_summary": ""
        }

        # Regime patterns
        for regime, stats in signal_data.get("by_regime", {}).items():
            insights["regime_understanding"][regime] = {
                "sample_size": stats.get("trades", 0),
                "observed_wr": stats.get("wr", 0),
                "quality": "good" if stats.get("wr", 0) > 50 else "poor",
                "recommendation": "prioritize" if stats.get("wr", 0) > 60 else "investigate"
            }

        # Setup patterns
        for setup, stats in signal_data.get("by_setup", {}).items():
            insights["setup_understanding"][setup] = {
                "sample_size": stats.get("trades", 0),
                "observed_wr": stats.get("wr", 0),
                "quality": "good" if stats.get("wr", 0) > 50 else "poor",
                "recommendation": "boost" if stats.get("wr", 0) > 60 else "gate"
            }

        insights["learning_summary"] = f"""
        Analyzed {signal_data.get('signals_generated', 0)} signals across {len(signal_data.get('by_regime', {}))} regimes.
        Executed {signal_data.get('signals_executed', 0)} trades with {signal_data.get('win_rate', 0):.1f}% win rate.

        Key patterns:
        - Best regime: {max((r for r, s in signal_data.get('by_regime', {}).items()), key=lambda x: signal_data['by_regime'][x].get('wr', 0), default='unknown')}
        - Best setup: {max((s for s, st in signal_data.get('by_setup', {}).items()), key=lambda x: signal_data['by_setup'][x].get('wr', 0), default='unknown')}
        - Worst regime: {min((r for r, s in signal_data.get('by_regime', {}).items()), key=lambda x: signal_data['by_regime'][x].get('wr', 0), default='unknown')}
        """

        return insights

    def update_knowledge_base(self, insights: Dict[str, Any], run_id: str):
        """Update agent knowledge base with new learnings."""

        kb_file = self.data_dir / "agent_knowledge_base.json"

        if kb_file.exists():
            with open(kb_file) as f:
                kb = json.load(f)
        else:
            kb = {"runs": [], "accumulated_patterns": {}}

        kb["runs"].append({
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "insights": insights
        })

        # Accumulate patterns
        for regime, understanding in insights.get("regime_understanding", {}).items():
            if regime not in kb["accumulated_patterns"]:
                kb["accumulated_patterns"][regime] = []
            kb["accumulated_patterns"][regime].append(understanding)

        with open(kb_file, 'w') as f:
            json.dump(kb, f, indent=2)

        logger.info(f"[RUN {run_id}] Knowledge base updated")

    def run_learning_cycle(self, cycle_num: int, symbols: List[str], days: int):
        """Run one complete learning cycle."""

        run_id = f"cycle_{cycle_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"\n{'='*60}")
        logger.info(f"LEARNING CYCLE {cycle_num}: {run_id}")
        logger.info(f"{'='*60}\n")

        # Step 1: Run backtest
        metrics = self.run_backtest(symbols, days, run_id)
        if not metrics:
            logger.error(f"Cycle {cycle_num} failed: backtest error")
            return False

        # Step 2: Extract signal data
        signal_data = self.extract_signal_data(metrics["raw_output"])
        logger.info(f"[RUN {run_id}] Extracted {signal_data.get('signals_generated', 0)} signals")

        # Step 3: Agent analysis
        insights = self.agent_analyze_patterns(signal_data)
        logger.info(f"[RUN {run_id}] Agent analysis complete")

        # Step 4: Update knowledge
        self.update_knowledge_base(insights, run_id)

        # Step 5: Log results
        results_file = self.backtest_results / f"{run_id}.json"
        with open(results_file, 'w') as f:
            json.dump({
                "metrics": metrics,
                "signal_data": signal_data,
                "insights": insights
            }, f, indent=2)

        logger.info(f"[RUN {run_id}] Cycle complete. Results: {results_file}\n")
        return True

    def run_autonomous_loop(self, symbols: List[str], num_cycles: int = 10, days_per_cycle: int = 365):
        """Run autonomous learning loop continuously."""

        logger.info("""
        ╔═══════════════════════════════════════════════════════════╗
        ║   AUTONOMOUS AGENT LEARNING LOOP                          ║
        ║   Running continuous backtests for agent understanding    ║
        ╚═══════════════════════════════════════════════════════════╝
        """)

        for cycle in range(1, num_cycles + 1):
            success = self.run_learning_cycle(cycle, symbols, days_per_cycle)

            if success:
                logger.info(f"✓ Cycle {cycle}/{num_cycles} complete")
            else:
                logger.error(f"✗ Cycle {cycle}/{num_cycles} failed")

            # Load and display accumulated knowledge
            kb_file = self.data_dir / "agent_knowledge_base.json"
            if kb_file.exists():
                with open(kb_file) as f:
                    kb = json.load(f)
                    logger.info(f"\nAccumulated knowledge from {len(kb['runs'])} runs:")
                    for regime in list(kb["accumulated_patterns"].keys())[:3]:
                        patterns = kb["accumulated_patterns"][regime]
                        avg_wr = sum(p.get('observed_wr', 0) for p in patterns) / len(patterns)
                        logger.info(f"  {regime}: avg WR {avg_wr:.1f}% ({len(patterns)} observations)")

        logger.info("\n" + "="*60)
        logger.info("AUTONOMOUS LEARNING LOOP COMPLETE")
        logger.info("="*60)


if __name__ == "__main__":
    import sys

    loop = AutonomousLearningLoop(bot_dir=".")

    # Run autonomous learning: 10 cycles of year-long backtests
    loop.run_autonomous_loop(
        symbols=["BTC", "ETH", "SOL", "HYPE"],
        num_cycles=10,
        days_per_cycle=365
    )
