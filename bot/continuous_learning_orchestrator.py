"""
Continuous Autonomous Learning Orchestrator
Runs multiple learning cycles in sequence, accumulating knowledge over time.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


class ContinuousLearningOrchestrator:
    """Orchestrates multiple autonomous learning cycles."""
    
    def __init__(self, bot_dir: str = "."):
        self.bot_dir = Path(bot_dir)
        self.data_dir = self.bot_dir / "data"
        self.knowledge_file = self.data_dir / "agent_knowledge_base.json"
    
    def run_continuous_cycles(self, num_cycles: int = 5, symbols: List[str] = None, days_per_cycle: int = 365):
        """Run continuous learning cycles, building accumulated knowledge."""
        
        if symbols is None:
            symbols = ["BTC", "ETH", "SOL", "HYPE"]
        
        logger.info(f"""
╔═══════════════════════════════════════════════════════════╗
║         CONTINUOUS AUTONOMOUS LEARNING SYSTEM             ║
║       Building Agent Understanding Over {num_cycles} Cycles                 ║
╚═══════════════════════════════════════════════════════════╝
        
Strategy: Run {num_cycles} learning cycles of {days_per_cycle}-day backtests
Agents will progressively understand system wiring
Each cycle: backtest → extract data → agent analysis → knowledge update
        """)
        
        from autonomous_learning_loop import AutonomousLearningLoop
        
        loop = AutonomousLearningLoop(bot_dir=str(self.bot_dir))
        
        for cycle_num in range(1, num_cycles + 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"CYCLE {cycle_num}/{num_cycles}")
            logger.info(f"{'='*60}")
            
            success = loop.run_learning_cycle(
                cycle_num=cycle_num,
                symbols=symbols,
                days=days_per_cycle
            )
            
            if success:
                # Load and display accumulated knowledge
                if self.knowledge_file.exists():
                    with open(self.knowledge_file) as f:
                        kb = json.load(f)
                        logger.info(f"\n✓ Cycle {cycle_num} complete")
                        logger.info(f"  Total runs: {len(kb.get('runs', []))}")
                        logger.info(f"  Accumulated patterns: {len(kb.get('accumulated_patterns', {}))}")
                        
                        # Show regime insights
                        patterns = kb.get('accumulated_patterns', {})
                        if patterns:
                            logger.info(f"  Regime patterns discovered:")
                            for regime, observations in list(patterns.items())[:3]:
                                wrs = [o.get('observed_wr', 0) for o in observations if isinstance(o, dict)]
                                if wrs:
                                    avg_wr = sum(wrs) / len(wrs)
                                    logger.info(f"    • {regime}: avg {avg_wr:.1f}% WR ({len(wrs)} obs)")
            else:
                logger.error(f"✗ Cycle {cycle_num} failed — stopping")
                break
        
        logger.info(f"\n{'='*60}")
        logger.info("CONTINUOUS LEARNING PHASE COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Knowledge accumulated in: {self.knowledge_file}")


if __name__ == "__main__":
    import sys
    
    orchestrator = ContinuousLearningOrchestrator(bot_dir=".")
    
    # Run 5 continuous cycles (could extend to 10+ for full multi-year learning)
    orchestrator.run_continuous_cycles(
        num_cycles=5,
        symbols=["BTC", "ETH", "SOL", "HYPE"],
        days_per_cycle=365
    )
