"""
Robust Learning Cycle Runner
Enhanced version of autonomous learning with better subprocess handling.
"""

import json
import subprocess
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RobustLearningCycle:
    """Run a single learning cycle with robust subprocess management."""

    def __init__(self, bot_dir: str = "."):
        self.bot_dir = Path(bot_dir)
        self.data_dir = self.bot_dir / "data"
        self.backtest_results = self.data_dir / "backtest_results"
        self.backtest_results.mkdir(parents=True, exist_ok=True)

    def run_backtest_with_monitoring(
        self,
        symbols: list,
        days: int,
        run_id: str,
        timeout_minutes: int = 180
    ) -> Optional[Dict[str, Any]]:
        """Run backtest with subprocess monitoring and timeout handling."""

        logger.info(f"[{run_id}] Starting backtest: {symbols}, {days} days")
        logger.info(f"[{run_id}] Timeout: {timeout_minutes} minutes")

        cmd = [
            "python", "run.py", "backtest",
            "--symbols", ",".join(symbols),
            "--days", str(days)
        ]

        try:
            start_time = time.time()
            logger.info(f"[{run_id}] Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_minutes * 60,
                cwd=self.bot_dir
            )

            elapsed = time.time() - start_time
            logger.info(f"[{run_id}] Backtest completed in {elapsed:.1f}s")

            if result.returncode != 0:
                logger.error(f"[{run_id}] Backtest failed with return code {result.returncode}")
                if result.stderr:
                    logger.error(f"[{run_id}] Stderr: {result.stderr[:500]}")
                return None

            # Parse output for metrics
            metrics = {
                "run_id": run_id,
                "timestamp": datetime.now().isoformat(),
                "symbols": symbols,
                "days": days,
                "elapsed_seconds": elapsed,
                "raw_output": result.stdout,
                "output_length": len(result.stdout)
            }

            logger.info(f"[{run_id}] Output: {len(result.stdout)} chars")
            return metrics

        except subprocess.TimeoutExpired:
            logger.error(f"[{run_id}] Backtest timed out after {timeout_minutes} minutes")
            return None
        except Exception as e:
            logger.error(f"[{run_id}] Backtest error: {str(e)}")
            return None

    def extract_signal_summary(self, backtest_output: str) -> Dict[str, Any]:
        """Extract signal summary from backtest output."""

        import re

        summary = {
            "signals_generated": None,
            "signals_executed": None,
            "win_rate": None,
            "by_regime": {},
            "by_setup": {},
        }

        # Extract signals
        if match := re.search(r"Signal gen:\s+(\d+)", backtest_output):
            summary["signals_generated"] = int(match.group(1))
        if match := re.search(r"Executed:\s+(\d+)", backtest_output):
            summary["signals_executed"] = int(match.group(1))
        if match := re.search(r"Win Rate.*?(\d+\.\d+)%", backtest_output):
            summary["win_rate"] = float(match.group(1))

        return summary

    def run_learning_cycle(
        self,
        cycle_num: int,
        symbols: list,
        days: int
    ) -> bool:
        """Run one complete learning cycle with all steps."""

        run_id = f"cycle_{cycle_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        logger.info("\n" + "=" * 70)
        logger.info(f"LEARNING CYCLE {cycle_num}: {run_id}")
        logger.info("=" * 70)

        # Step 1: Run backtest
        logger.info(f"\n[STEP 1] Running {days}-day backtest...")
        metrics = self.run_backtest_with_monitoring(
            symbols=symbols,
            days=days,
            run_id=run_id,
            timeout_minutes=180  # 3 hours for year-long backtest
        )

        if not metrics:
            logger.error(f"[CYCLE {cycle_num}] Backtest failed — stopping")
            return False

        # Step 2: Extract signal data
        logger.info(f"\n[STEP 2] Extracting signal data...")
        signal_summary = self.extract_signal_summary(metrics["raw_output"])
        logger.info(f"  Signals generated: {signal_summary.get('signals_generated', 'unknown')}")
        logger.info(f"  Signals executed: {signal_summary.get('signals_executed', 'unknown')}")
        logger.info(f"  Win rate: {signal_summary.get('win_rate', 'unknown'):.1f}%")

        # Step 3: Save results
        logger.info(f"\n[STEP 3] Saving cycle results...")
        results_file = self.backtest_results / f"{run_id}.json"
        cycle_data = {
            "metrics": metrics,
            "signal_summary": signal_summary,
            "cycle_num": cycle_num
        }

        with open(results_file, 'w') as f:
            json.dump(cycle_data, f, indent=2)
        logger.info(f"  Saved: {results_file}")

        # Step 4: Update knowledge base (optional)
        logger.info(f"\n[STEP 4] Updating knowledge base...")
        kb_file = self.data_dir / "agent_knowledge_base.json"
        if kb_file.exists():
            with open(kb_file) as f:
                kb = json.load(f)
        else:
            kb = {"runs": [], "accumulated_patterns": {}}

        kb["runs"].append({
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "cycle_num": cycle_num,
            "signal_summary": signal_summary
        })

        with open(kb_file, 'w') as f:
            json.dump(kb, f, indent=2)
        logger.info(f"  Knowledge base updated ({len(kb['runs'])} total runs)")

        logger.info(f"\n[CYCLE {cycle_num}] COMPLETE ✓")
        logger.info("=" * 70 + "\n")

        return True


if __name__ == "__main__":
    runner = RobustLearningCycle(bot_dir=".")

    # Run single cycle
    success = runner.run_learning_cycle(
        cycle_num=1,
        symbols=["BTC", "ETH", "SOL", "HYPE"],
        days=365
    )

    if success:
        print("\nCycle 1 complete. Knowledge base saved.")
        print("To run continuous cycles: python continuous_learning_orchestrator.py")
    else:
        print("\nCycle 1 failed. Check logs above.")
