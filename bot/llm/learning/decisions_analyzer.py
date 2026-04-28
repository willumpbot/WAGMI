"""Decisions Analyzer - CLI utilities for analyzing audit trail.

Provides insights from decisions.jsonl: win rates by symbol/regime/pattern,
overconfidence detection, regime transitions, etc.

Usage:
  python -m llm.learning.decisions_analyzer --since 7d --metric wr
  python -m llm.learning.decisions_analyzer --pattern "trending_bear+3-agree"
  python -m llm.learning.decisions_analyzer --overconfident
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class DecisionsAnalyzer:
    """Analyze decisions.jsonl audit trail."""

    def __init__(self, decisions_path: str = "bot/data/llm/decisions.jsonl"):
        self.decisions_path = Path(decisions_path)
        self._decisions = None

    def _load_decisions(self) -> List[Dict[str, Any]]:
        """Load all decision entries from JSONL."""
        if self._decisions is not None:
            return self._decisions

        self._decisions = []
        if not self.decisions_path.exists():
            logger.warning(f"Decisions file not found: {self.decisions_path}")
            return self._decisions

        try:
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        self._decisions.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to load decisions: {e}")

        return self._decisions

    def summarize_by_symbol(
        self,
        since_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Summarize decision accuracy by symbol.

        Returns:
            Dict mapping symbol → {win_rate, trade_count, avg_confidence, etc.}
        """
        decisions = self._load_decisions()
        if not decisions:
            return {}

        cutoff = None
        if since_days:
            cutoff = datetime.utcnow() - timedelta(days=since_days)

        by_symbol = defaultdict(
            lambda: {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "avg_confidence": 0.0,
                "total_confidence": 0.0,
                "symbols_by_regime": defaultdict(lambda: {"trades": 0, "wins": 0}),
            }
        )

        for decision in decisions:
            if cutoff:
                ts_str = decision.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    except ValueError:
                        continue

            symbol = decision.get("symbol", "unknown")
            action = decision.get("action", "")
            regime = decision.get("regime", "unknown")
            confidence = decision.get("confidence", 0.0)

            # Track by symbol
            stats = by_symbol[symbol]
            stats["trades"] += 1
            stats["total_confidence"] += confidence

            # Track by regime within symbol
            regime_stats = stats["symbols_by_regime"][regime]
            regime_stats["trades"] += 1

            # Assume action="go" and positive outcome = win
            # (In reality, would cross-reference with closed trades)
            if action == "go":
                stats["wins"] += 1
                regime_stats["wins"] += 1
            else:
                stats["losses"] += 1

        # Compute final stats
        result = {}
        for symbol, stats in by_symbol.items():
            total = stats["trades"]
            result[symbol] = {
                "win_rate": stats["wins"] / total if total > 0 else 0.0,
                "trade_count": total,
                "avg_confidence": (
                    stats["total_confidence"] / total if total > 0 else 0.0
                ),
                "regime_breakdown": dict(stats["symbols_by_regime"]),
            }

        return result

    def summarize_by_regime(
        self,
        since_days: Optional[int] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Summarize decision accuracy by regime.

        Returns:
            Dict mapping regime → {win_rate, trade_count, symbol_breakdown, etc.}
        """
        decisions = self._load_decisions()
        if not decisions:
            return {}

        cutoff = None
        if since_days:
            cutoff = datetime.utcnow() - timedelta(days=since_days)

        by_regime = defaultdict(
            lambda: {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "avg_confidence": 0.0,
                "total_confidence": 0.0,
                "symbols": defaultdict(lambda: {"trades": 0, "wins": 0}),
            }
        )

        for decision in decisions:
            if cutoff:
                ts_str = decision.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    except ValueError:
                        continue

            regime = decision.get("regime", "unknown")
            symbol = decision.get("symbol", "unknown")
            action = decision.get("action", "")
            confidence = decision.get("confidence", 0.0)

            stats = by_regime[regime]
            stats["trades"] += 1
            stats["total_confidence"] += confidence

            symbol_stats = stats["symbols"][symbol]
            symbol_stats["trades"] += 1

            if action == "go":
                stats["wins"] += 1
                symbol_stats["wins"] += 1
            else:
                stats["losses"] += 1

        result = {}
        for regime, stats in by_regime.items():
            total = stats["trades"]
            result[regime] = {
                "win_rate": stats["wins"] / total if total > 0 else 0.0,
                "trade_count": total,
                "avg_confidence": (
                    stats["total_confidence"] / total if total > 0 else 0.0
                ),
                "symbol_breakdown": dict(stats["symbols"]),
            }

        return result

    def summarize_by_pattern(
        self,
        pattern: str,
        since_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Summarize a specific pattern (regime+n_agree+confidence).

        Args:
            pattern: Pattern like "trending_bear+3-agree+80conf"
            since_days: Optional lookback window

        Returns:
            Dict with pattern performance: {win_rate, sample_size, last_trades, etc.}
        """
        decisions = self._load_decisions()
        if not decisions:
            return {"error": "No decisions found"}

        cutoff = None
        if since_days:
            cutoff = datetime.utcnow() - timedelta(days=since_days)

        matching = []
        for decision in decisions:
            if cutoff:
                ts_str = decision.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    except ValueError:
                        continue

            # Check if decision matches pattern
            regime = decision.get("regime", "")
            n_agree = decision.get("n_agree", 0)
            confidence = decision.get("confidence", 0.0)

            # Build pattern from decision (confidence is 0-100 scale)
            conf_bin = int(confidence / 10) * 10
            decision_pattern = f"{regime}+{n_agree}-agree+{conf_bin}conf"

            if decision_pattern == pattern:
                matching.append(decision)

        if not matching:
            return {"error": f"No trades found for pattern: {pattern}"}

        wins = sum(1 for d in matching if d.get("action") == "go")
        total = len(matching)

        return {
            "pattern": pattern,
            "win_rate": wins / total if total > 0 else 0.0,
            "sample_size": total,
            "wins": wins,
            "losses": total - wins,
            "last_trade_time": matching[-1].get("timestamp") if matching else None,
            "first_trade_time": matching[0].get("timestamp") if matching else None,
        }

    def identify_overconfident_bins(
        self,
        since_days: Optional[int] = None,
        threshold: float = 0.15,
    ) -> Dict[str, Dict[str, Any]]:
        """Identify confidence bins where predicted > actual.

        Args:
            since_days: Optional lookback window
            threshold: Gap threshold (0.15 = 15% overconfidence)

        Returns:
            Dict mapping confidence_bin → {predicted, actual, gap, count}
        """
        decisions = self._load_decisions()
        if not decisions:
            return {}

        cutoff = None
        if since_days:
            cutoff = datetime.utcnow() - timedelta(days=since_days)

        bins = defaultdict(lambda: {"trades": 0, "wins": 0})

        for decision in decisions:
            if cutoff:
                ts_str = decision.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    except ValueError:
                        continue

            confidence = decision.get("confidence", 0.0)
            action = decision.get("action", "")

            # Bin to nearest 10 (confidence is 0-100 scale)
            conf_bin = int(confidence / 10) * 10
            bin_key = f"{conf_bin}-{conf_bin + 10}"

            bins[bin_key]["trades"] += 1
            if action == "go":
                bins[bin_key]["wins"] += 1

        # Compute gaps
        overconfident = {}
        for bin_key, stats in bins.items():
            if stats["trades"] < 3:
                continue

            actual_wr = stats["wins"] / stats["trades"]
            predicted = (int(bin_key.split("-")[0]) + int(bin_key.split("-")[1])) / 200
            gap = predicted - actual_wr

            if gap > threshold:
                overconfident[bin_key] = {
                    "predicted": predicted,
                    "actual": actual_wr,
                    "gap": gap,
                    "sample_size": stats["trades"],
                }

        return overconfident

    def find_regime_transitions(
        self,
        window_trades: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find regime transitions in decision history.

        Args:
            window_trades: Lookback window in trades

        Returns:
            List of transitions: [{timestamp, from_regime, to_regime, trade_num}, ...]
        """
        decisions = self._load_decisions()
        if not decisions:
            return []

        # Extract only recent decisions
        recent = decisions[-window_trades:] if len(decisions) > window_trades else decisions

        transitions = []
        prev_regime = None

        for i, decision in enumerate(recent):
            regime = decision.get("regime", "unknown")

            if prev_regime and prev_regime != regime:
                transitions.append(
                    {
                        "trade_number": len(decisions) - window_trades + i,
                        "from_regime": prev_regime,
                        "to_regime": regime,
                        "timestamp": decision.get("timestamp"),
                    }
                )

            prev_regime = regime

        return transitions


def main():
    """CLI interface for decisions analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze decisions.jsonl audit trail")
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help="Lookback window in days",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Filter by symbol",
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="wr",
        choices=["wr", "count", "conf"],
        help="Metric to show",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default=None,
        help="Analyze specific pattern (e.g., trending_bear+3-agree+80conf)",
    )
    parser.add_argument(
        "--overconfident",
        action="store_true",
        help="Show overconfident bins",
    )
    parser.add_argument(
        "--regime",
        type=str,
        default=None,
        help="Filter by regime",
    )

    args = parser.parse_args()

    analyzer = DecisionsAnalyzer()

    if args.pattern:
        result = analyzer.summarize_by_pattern(args.pattern, since_days=args.since)
        print(json.dumps(result, indent=2))
    elif args.overconfident:
        result = analyzer.identify_overconfident_bins(since_days=args.since)
        print(json.dumps(result, indent=2))
    elif args.symbol:
        result = analyzer.summarize_by_symbol(since_days=args.since)
        if args.symbol in result:
            print(f"{args.symbol}: {json.dumps(result[args.symbol], indent=2)}")
        else:
            print(f"No data for {args.symbol}")
    elif args.regime:
        result = analyzer.summarize_by_regime(since_days=args.since)
        if args.regime in result:
            print(f"{args.regime}: {json.dumps(result[args.regime], indent=2)}")
        else:
            print(f"No data for {args.regime}")
    else:
        # Default: show by regime
        result = analyzer.summarize_by_regime(since_days=args.since)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
