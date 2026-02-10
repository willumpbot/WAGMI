"""
Signal performance validator and analytics.

Links signals to trade outcomes. Calculates win rates by:
- Symbol
- Regime alignment strength
- Strategy consensus
- Time of day
- Confidence tier
- Market condition

Output: signal_outcomes.csv with full tracing
"""

import logging
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import pandas as pd
import numpy as np

logger = logging.getLogger("bot.execution.signal_validator")


@dataclass
class SignalOutcome:
    """Linked outcome for a signal."""
    signal_id: str
    timestamp: str
    symbol: str
    direction: str  # BUY or SELL
    entry_price: float
    confidence: float
    regime_score: float
    strategy_consensus: int  # how many agreed
    num_strategies: int
    status: str  # FILLED, MISSED, or result
    actual_entry: Optional[float] = None
    actual_exit: Optional[float] = None
    outcome: Optional[str] = None  # WIN, LOSS, BREAK_EVEN, MISSED
    pnl: Optional[float] = None
    duration_hours: Optional[float] = None
    exit_action: Optional[str] = None  # TP1, TP2, SL, TRAILING_STOP


class SignalValidator:
    """Matches signals to trade outcomes."""

    def __init__(self, signal_dir: str = "paper_trades", match_window_min: int = 120):
        self.signal_dir = Path(signal_dir)
        self.match_window_min = match_window_min  # Time to match signal to trade
        self.signal_df = None
        self.trade_df = None
        self.outcomes = []

        self._load_data()

    def _load_data(self):
        """Load latest signal and trade CSVs."""
        signals_files = sorted(list(self.signal_dir.glob("signals_*.csv")))
        trades_files = sorted(list(self.signal_dir.glob("trades_*.csv")))

        if signals_files:
            try:
                self.signal_df = pd.read_csv(signals_files[-1])
                self.signal_df["timestamp"] = pd.to_datetime(self.signal_df["timestamp"])
                self.signal_df = self.signal_df.sort_values("timestamp")
                logger.info(f"✅ Loaded {len(self.signal_df)} signals")
            except Exception as e:
                logger.warning(f"Could not load signals: {e}")

        if trades_files:
            try:
                self.trade_df = pd.read_csv(trades_files[-1])
                self.trade_df["timestamp"] = pd.to_datetime(self.trade_df["timestamp"])
                self.trade_df = self.trade_df.sort_values("timestamp")
                logger.info(f"✅ Loaded {len(self.trade_df)} trades")
            except Exception as e:
                logger.warning(f"Could not load trades: {e}")

    def validate(self) -> List[SignalOutcome]:
        """Match signals to trades and generate outcomes."""
        if self.signal_df is None or self.trade_df is None:
            logger.warning("Missing signal or trade data")
            return []

        outcomes = []

        for idx, signal in self.signal_df.iterrows():
            signal_id = f"{signal['symbol']}_{signal['timestamp'].isoformat()}"
            symbol = signal["symbol"].upper()
            signal_ts = signal["timestamp"]
            signal_dir = signal["side"]
            entry_price = signal["entry"]
            confidence = signal["confidence"]
            regime_score = signal.get("regime_score", 0)
            num_agree = signal.get("num_agree", 1)
            total_strats = signal.get("total_strategies", 4)

            # Find if this signal was acted on (position opened)
            matching_trades = self.trade_df[
                (self.trade_df["symbol"] == symbol)
                & (self.trade_df["action"] == "OPEN")
                & (self.trade_df["timestamp"] >= signal_ts)
                & (self.trade_df["timestamp"] <= signal_ts + timedelta(minutes=self.match_window_min))
            ]

            if matching_trades.empty:
                # Signal was not traded (missed)
                outcome = SignalOutcome(
                    signal_id=signal_id,
                    timestamp=signal_ts.isoformat(),
                    symbol=symbol,
                    direction=signal_dir,
                    entry_price=entry_price,
                    confidence=confidence,
                    regime_score=regime_score,
                    strategy_consensus=num_agree,
                    num_strategies=total_strats,
                    status="MISSED",
                    outcome="MISSED",
                )
                outcomes.append(outcome)
                continue

            # Signal was filled - find the exit
            open_trade = matching_trades.iloc[0]
            open_ts = open_trade["timestamp"]
            open_price = open_trade["price"]

            # Find corresponding close trade
            closing = self.trade_df[
                (self.trade_df["symbol"] == symbol)
                & (self.trade_df["action"].isin(["TP1", "TP2", "SL", "TRAILING_STOP"]))
                & (self.trade_df["timestamp"] > open_ts)
            ]

            if closing.empty:
                # Position still open
                outcome = SignalOutcome(
                    signal_id=signal_id,
                    timestamp=signal_ts.isoformat(),
                    symbol=symbol,
                    direction=signal_dir,
                    entry_price=entry_price,
                    confidence=confidence,
                    regime_score=regime_score,
                    strategy_consensus=num_agree,
                    num_strategies=total_strats,
                    status="FILLED",
                    actual_entry=open_price,
                    outcome="OPEN",
                )
                outcomes.append(outcome)
                continue

            # Signal was filled and closed
            close_trade = closing.iloc[0]
            close_ts = close_trade["timestamp"]
            close_price = close_trade["price"]
            pnl = close_trade["pnl"]
            exit_action = close_trade["action"]

            duration = (close_ts - open_ts).total_seconds() / 3600  # hours

            # Determine outcome
            if pnl > 0:
                result = "WIN"
            elif pnl < 0:
                result = "LOSS"
            else:
                result = "BREAK_EVEN"

            outcome = SignalOutcome(
                signal_id=signal_id,
                timestamp=signal_ts.isoformat(),
                symbol=symbol,
                direction=signal_dir,
                entry_price=entry_price,
                confidence=confidence,
                regime_score=regime_score,
                strategy_consensus=num_agree,
                num_strategies=total_strats,
                status="FILLED",
                actual_entry=open_price,
                actual_exit=close_price,
                outcome=result,
                pnl=pnl,
                duration_hours=duration,
                exit_action=exit_action,
            )
            outcomes.append(outcome)

        self.outcomes = outcomes
        logger.info(f"✅ Validated {len(outcomes)} signals")

        # Save outcomes
        self._save_outcomes()

        return outcomes

    def _save_outcomes(self):
        """Save outcomes to CSV."""
        if not self.outcomes:
            return

        output_file = self.signal_dir / f"signal_outcomes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df = pd.DataFrame([asdict(o) for o in self.outcomes])
        df.to_csv(output_file, index=False)
        logger.info(f"✅ Saved outcomes to {output_file}")


class SignalAnalytics:
    """Analyze signal performance."""

    def __init__(self, outcomes: List[SignalOutcome]):
        self.outcomes = outcomes
        self.df = pd.DataFrame([asdict(o) for o in outcomes]) if outcomes else pd.DataFrame()

    def win_rate_by_symbol(self) -> Dict[str, float]:
        """Calculate win rate for each symbol."""
        if self.df.empty:
            return {}

        closed = self.df[self.df["status"] == "FILLED"]
        results = {}

        for symbol in closed["symbol"].unique():
            sym_trades = closed[closed["symbol"] == symbol]
            wins = len(sym_trades[sym_trades["outcome"] == "WIN"])
            total = len(sym_trades)
            results[symbol] = wins / total * 100 if total > 0 else 0

        return results

    def win_rate_by_regime(self) -> Dict[int, float]:
        """Calculate win rate by regime strength (star rating)."""
        if self.df.empty:
            return {}

        closed = self.df[self.df["status"] == "FILLED"]
        closed["regime_tier"] = closed["regime_score"].round().astype(int)

        results = {}
        for tier in sorted(closed["regime_tier"].unique()):
            tier_trades = closed[closed["regime_tier"] == tier]
            wins = len(tier_trades[tier_trades["outcome"] == "WIN"])
            total = len(tier_trades)
            results[tier] = wins / total * 100 if total > 0 else 0

        return results

    def win_rate_by_consensus(self) -> Dict[int, float]:
        """Calculate win rate by how many strategies agreed."""
        if self.df.empty:
            return {}

        closed = self.df[self.df["status"] == "FILLED"]
        results = {}

        for consensus in sorted(closed["strategy_consensus"].unique()):
            con_trades = closed[closed["strategy_consensus"] == consensus]
            wins = len(con_trades[con_trades["outcome"] == "WIN"])
            total = len(con_trades)
            results[consensus] = wins / total * 100 if total > 0 else 0

        return results

    def win_rate_by_confidence(self) -> Dict[str, Tuple[float, int]]:
        """Calculate win rate by confidence tier."""
        if self.df.empty:
            return {}

        closed = self.df[self.df["status"] == "FILLED"]

        # Define tiers
        tiers = {
            "70-80%": (70, 80),
            "80-90%": (80, 90),
            "90%+": (90, 100),
            "<70%": (0, 70),
        }

        results = {}
        for tier_name, (low, high) in tiers.items():
            tier_trades = closed[(closed["confidence"] >= low) & (closed["confidence"] < high)]
            if tier_trades.empty:
                continue

            wins = len(tier_trades[tier_trades["outcome"] == "WIN"])
            total = len(tier_trades)
            win_rate = wins / total * 100 if total > 0 else 0
            results[tier_name] = (win_rate, total)

        return results

    def best_signals(self, top_n: int = 10) -> List[SignalOutcome]:
        """Return top N most profitable signals."""
        closed = self.df[self.df["status"] == "FILLED"].copy()
        if closed.empty:
            return []

        closed = closed.sort_values("pnl", ascending=False)
        return [
            SignalOutcome(**row.to_dict())
            for _, row in closed.head(top_n).iterrows()
        ]

    def worst_signals(self, top_n: int = 10) -> List[SignalOutcome]:
        """Return bottom N most losing signals."""
        closed = self.df[self.df["status"] == "FILLED"].copy()
        if closed.empty:
            return []

        closed = closed.sort_values("pnl", ascending=True)
        return [
            SignalOutcome(**row.to_dict())
            for _, row in closed.head(top_n).iterrows()
        ]

    def missed_signals(self) -> int:
        """Return count of signals that were not acted on."""
        return len(self.df[self.df["outcome"] == "MISSED"])

    def print_report(self):
        """Print full analysis report."""
        if self.df.empty:
            print("❌ No signal outcomes to analyze")
            return

        closed = self.df[self.df["status"] == "FILLED"]
        total_signals = len(self.df)
        filled_signals = len(closed)
        missed_signals = self.missed_signals()

        print("\n" + "=" * 60)
        print("SIGNAL PERFORMANCE ANALYSIS")
        print("=" * 60)

        print(f"\n📊 OVERVIEW:")
        print(f"  Total Signals: {total_signals}")
        print(f"  Filled: {filled_signals} | Missed: {missed_signals}")

        if filled_signals > 0:
            wins = len(closed[closed["outcome"] == "WIN"])
            losses = len(closed[closed["outcome"] == "LOSS"])
            breakeven = len(closed[closed["outcome"] == "BREAK_EVEN"])
            win_rate = wins / filled_signals * 100
            avg_pnl = closed["pnl"].mean()

            print(f"  Filled Signals: {wins} wins, {losses} losses, {breakeven} break-even")
            print(f"  Win Rate: {win_rate:.1f}%")
            print(f"  Avg P&L per signal: ${avg_pnl:+.2f}")

            print(f"\n🎯 BY REGIME STRENGTH:")
            by_regime = self.win_rate_by_regime()
            for regime in sorted(by_regime.keys()):
                stars = "⭐" * regime + "☆" * (5 - regime)
                print(f"  {stars}: {by_regime[regime]:.1f}%")

            print(f"\n👥 BY STRATEGY CONSENSUS:")
            by_consensus = self.win_rate_by_consensus()
            for consensus in sorted(by_consensus.keys()):
                print(f"  {consensus}/4 agree: {by_consensus[consensus]:.1f}%")

            print(f"\n💯 BY CONFIDENCE TIER:")
            by_conf = self.win_rate_by_confidence()
            for tier in ["<70%", "70-80%", "80-90%", "90%+"]:
                if tier in by_conf:
                    wr, count = by_conf[tier]
                    print(f"  {tier}: {wr:.1f}% ({count} trades)")

            print(f"\n📈 BY SYMBOL:")
            by_symbol = self.win_rate_by_symbol()
            for symbol in sorted(by_symbol.keys()):
                print(f"  {symbol}: {by_symbol[symbol]:.1f}%")

        print("\n" + "=" * 60 + "\n")


def main():
    """Run signal validation and print report."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate signals and analyze performance")
    parser.add_argument("--dir", default="paper_trades", help="Paper trades directory")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    validator = SignalValidator(args.dir)
    outcomes = validator.validate()

    analytics = SignalAnalytics(outcomes)
    analytics.print_report()


if __name__ == "__main__":
    main()
