"""
Signal Curator: Daily signal ranking and manual trading execution tracker.

Modules:
- signal_ranker: Ranks daily signals by confidence, setup type, multi-agree consensus
- execution_tracker: Records manual fills and measures execution alpha vs signal alpha
- cli: Command-line interface for curating signals and tracking trades

Usage:
  cd bot
  python -c "from curator.cli import main; main()" show-signals
  python -c "from curator.cli import main; main()" log-execution sig_001 45632.50 0.01
  python -c "from curator.cli import main; main()" log-close sig_001 46200.75
  python -c "from curator.cli import main; main()" report
  python -c "from curator.cli import main; main()" status
"""

from .signal_ranker import SignalRanker, RankedSignal
from .execution_tracker import ExecutionTracker, SignalRecord, ExecutionStatus
from .cli import CuratorCLI, main

__all__ = [
    "SignalRanker",
    "RankedSignal",
    "ExecutionTracker",
    "SignalRecord",
    "ExecutionStatus",
    "CuratorCLI",
    "main",
]
