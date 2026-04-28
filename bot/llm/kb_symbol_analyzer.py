"""
KB Symbol Analyzer - Extract symbol-specific KB parameters from trade outcomes.

Analyzes trade results by symbol to build symbol-specific confidence thresholds,
win rates, and performance profiles.
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime


class KBSymbolAnalyzer:
    """Analyze trade outcomes by symbol to extract symbol-specific parameters."""

    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.trades_file = self.data_dir / "trades.csv"
        self.decisions_file = self.data_dir / "llm" / "decisions.jsonl"

    def load_trades_by_symbol(self):
        """Load trades from trades.csv grouped by symbol."""
        if not self.trades_file.exists():
            return {}

        trades_by_symbol = defaultdict(list)
        try:
            with open(self.trades_file) as f:
                lines = f.readlines()
                if not lines:
                    return {}

                # Skip header
                for line in lines[1:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 3:
                        symbol = parts[0]
                        side = parts[1]
                        # Assuming outcome is pnl or win/loss indicator
                        try:
                            outcome = float(parts[-2]) if len(parts) > 2 else 0
                            trades_by_symbol[symbol].append({
                                "side": side,
                                "outcome": outcome,
                                "win": outcome > 0
                            })
                        except (ValueError, IndexError):
                            pass
        except Exception as e:
            print(f"[KB-ANALYZER] Error loading trades: {e}")

        return trades_by_symbol

    def load_decisions_by_symbol(self):
        """Load decisions from decisions.jsonl grouped by symbol."""
        if not self.decisions_file.exists():
            return {}

        decisions_by_symbol = defaultdict(list)
        try:
            with open(self.decisions_file) as f:
                for line in f:
                    try:
                        decision = json.loads(line)
                        symbol = decision.get("symbol", "UNKNOWN")
                        action = decision.get("a", "skip").lower()
                        confidence = float(decision.get("c", 50))
                        outcome = decision.get("outcome")  # If available

                        decisions_by_symbol[symbol].append({
                            "action": action,
                            "confidence": confidence,
                            "outcome": outcome,
                        })
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"[KB-ANALYZER] Error loading decisions: {e}")

        return decisions_by_symbol

    def compute_symbol_stats(self, trades_by_symbol):
        """Compute win rates, optimal thresholds, and volatility profiles by symbol."""
        symbol_stats = {}

        for symbol, trades in trades_by_symbol.items():
            if not trades:
                continue

            wins = sum(1 for t in trades if t["win"])
            total = len(trades)
            win_rate = wins / total if total > 0 else 0

            # Compute volatility profile based on outcome distribution
            outcomes = [t["outcome"] for t in trades]
            avg_outcome = sum(outcomes) / len(outcomes) if outcomes else 0
            volatility = max(outcomes) - min(outcomes) if outcomes else 0

            # Profile categories
            if volatility > 2000:
                volatility_profile = "high"
            elif volatility > 500:
                volatility_profile = "medium"
            else:
                volatility_profile = "low"

            symbol_stats[symbol] = {
                "trade_count": total,
                "win_count": wins,
                "win_rate": win_rate,
                "avg_outcome": avg_outcome,
                "volatility": volatility,
                "volatility_profile": volatility_profile,
                "optimal_threshold": self._compute_optimal_threshold(win_rate),
                "go_win_rate": win_rate if win_rate > 0.45 else 0.45,
                "skip_win_rate": min(win_rate * 0.4, 0.25),  # Conservative estimate
            }

        return symbol_stats

    def _compute_optimal_threshold(self, win_rate):
        """Compute optimal confidence threshold based on win rate."""
        # Scale confidence threshold based on symbol win rate
        if win_rate >= 0.60:
            return 35  # Lower threshold for high-WR symbols
        elif win_rate >= 0.50:
            return 40
        elif win_rate >= 0.40:
            return 45
        else:
            return 50  # Higher threshold for lower-WR symbols

    def build_symbol_kb(self, trades_by_symbol, decisions_by_symbol):
        """Build symbol-specific KB section."""
        symbol_stats = self.compute_symbol_stats(trades_by_symbol)

        # Also incorporate decision-level insights
        for symbol in decisions_by_symbol:
            decisions = decisions_by_symbol[symbol]
            if not decisions:
                continue

            # Compute decision-level stats
            go_decisions = [d for d in decisions if d["action"] in ("go", "proceed")]
            skip_decisions = [d for d in decisions if d["action"] in ("skip", "flat")]

            go_count = len(go_decisions)
            skip_count = len(skip_decisions)

            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    "trade_count": 0,
                    "win_count": 0,
                    "win_rate": 0,
                    "volatility_profile": "normal",
                }

            # Merge decision insights
            symbol_stats[symbol]["decision_count"] = len(decisions)
            symbol_stats[symbol]["go_decision_count"] = go_count
            symbol_stats[symbol]["skip_decision_count"] = skip_count
            symbol_stats[symbol]["avg_confidence"] = (
                sum(d["confidence"] for d in decisions) / len(decisions)
                if decisions
                else 50
            )

        return symbol_stats

    def update_kb_with_symbols(self, kb_config):
        """Inject symbol-specific stats into KB config."""
        trades_by_symbol = self.load_trades_by_symbol()
        decisions_by_symbol = self.load_decisions_by_symbol()

        symbol_stats = self.build_symbol_kb(trades_by_symbol, decisions_by_symbol)

        if symbol_stats:
            kb_config["symbol_statistics"] = symbol_stats
            kb_config["symbol_statistics_updated"] = datetime.now().isoformat()

        return kb_config

    def analyze_and_report(self):
        """Analyze symbol performance and print report."""
        trades_by_symbol = self.load_trades_by_symbol()
        decisions_by_symbol = self.load_decisions_by_symbol()
        symbol_stats = self.build_symbol_kb(trades_by_symbol, decisions_by_symbol)

        print("=" * 100)
        print("SYMBOL-SPECIFIC KB ANALYSIS")
        print("=" * 100)

        for symbol in sorted(symbol_stats.keys()):
            stats = symbol_stats[symbol]
            print(f"\n{symbol}:")
            print(f"  Trades: {stats.get('trade_count', 0)} | WR: {stats.get('win_rate', 0):.1%}")
            print(f"  Confidence: {stats.get('avg_confidence', 50):.0f}")
            print(f"  Optimal Threshold: {stats.get('optimal_threshold', 45)}")
            print(f"  Volatility: {stats.get('volatility_profile', 'normal')}")
            print(f"  Expected GO WR: {stats.get('go_win_rate', 0.50):.1%}")
            print(f"  Expected SKIP WR: {stats.get('skip_win_rate', 0.221):.1%}")

        print("\n" + "=" * 100)


def enhance_kb_with_symbols(kb_config_path, output_path=None):
    """Enhance an existing KB file with symbol-specific parameters."""
    analyzer = KBSymbolAnalyzer(data_dir="data")

    with open(kb_config_path) as f:
        kb_config = json.load(f)

    kb_config = analyzer.update_kb_with_symbols(kb_config)

    output_file = output_path or kb_config_path.replace(".json", "_WITH_SYMBOLS.json")
    with open(output_file, "w") as f:
        json.dump(kb_config, f, indent=2)

    print(f"[KB-ANALYZER] Enhanced KB written to {output_file}")
    return kb_config


if __name__ == "__main__":
    analyzer = KBSymbolAnalyzer(data_dir="data")
    analyzer.analyze_and_report()
