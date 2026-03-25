"""
Manual Trade Performance Analyzer.

Compares actual manual trades against sniper signals to measure:
- Signal accuracy (did price hit TP before SL?)
- Execution quality (slippage from signal entry)
- System grading (how profitable if you followed signals exactly)
- Weekly/daily P&L breakdown
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.manual.performance")

_SIGNALS_PATH = os.path.join("data", "manual", "sniper_signals.jsonl")


def _load_sniper_signals() -> List[Dict[str, Any]]:
    """Load all sniper signals from JSONL log."""
    signals = []
    if not os.path.exists(_SIGNALS_PATH):
        return signals
    try:
        with open(_SIGNALS_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        signals.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.warning(f"Failed to load sniper signals: {e}")
    return signals


class PerformanceAnalyzer:
    """
    Compares actual manual trades against sniper signals.

    Measures execution quality, signal accuracy, and system edge.
    """

    def __init__(self, journal=None):
        """
        Args:
            journal: TradeJournal instance (lazy-loaded if None)
        """
        self._journal = journal

    @property
    def journal(self):
        if self._journal is None:
            from manual.trade_journal import get_trade_journal
            self._journal = get_trade_journal()
        return self._journal

    def get_signal_accuracy(self) -> Dict[str, Any]:
        """
        Analyze sniper signal accuracy based on actual trade outcomes.

        For each signal that was traded, check if the actual outcome
        matched what the signal predicted (TP hit vs SL hit).
        """
        signals = _load_sniper_signals()
        closed = self.journal.get_closed_trades()

        if not signals:
            return {
                "total_signals": 0,
                "signals_traded": 0,
                "signals_skipped": 0,
                "accuracy": 0,
                "details": [],
            }

        # Match trades to signals by symbol/side/time proximity
        traded_signals = []
        traded_signal_ids = set()

        for trade in closed:
            if not trade.signal_id:
                continue
            # Find matching signal
            for sig in signals:
                sig_ts = sig.get("timestamp", "")
                if trade.signal_id and trade.signal_id == sig.get("signal_id"):
                    traded_signals.append((sig, trade))
                    traded_signal_ids.add(id(sig))
                    break

        # Also match by symbol+side+time proximity
        for trade in closed:
            if trade.signal_id:
                continue
            entry_time = datetime.fromisoformat(trade.entry_time) if trade.entry_time else None
            if not entry_time:
                continue
            for sig in signals:
                if id(sig) in traded_signal_ids:
                    continue
                if sig.get("symbol") != trade.symbol or sig.get("side") != trade.side:
                    continue
                sig_time = datetime.fromisoformat(sig.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if abs((entry_time - sig_time).total_seconds()) < 3600:  # Within 1 hour
                    traded_signals.append((sig, trade))
                    traded_signal_ids.add(id(sig))
                    break

        # Calculate accuracy
        correct = 0
        details = []
        for sig, trade in traded_signals:
            was_profitable = trade.pnl is not None and trade.pnl > 0

            # Slippage analysis
            sig_entry = sig.get("entry", 0)
            slippage = 0
            slippage_pct = 0
            if sig_entry > 0:
                slippage = trade.entry_price - sig_entry
                slippage_pct = slippage / sig_entry * 100

            if was_profitable:
                correct += 1

            details.append({
                "symbol": trade.symbol,
                "side": trade.side,
                "signal_entry": sig_entry,
                "actual_entry": trade.entry_price,
                "slippage_pct": round(slippage_pct, 3),
                "signal_tp_scalp": sig.get("tp_scalp", 0),
                "actual_exit": trade.exit_price,
                "pnl": trade.pnl,
                "profitable": was_profitable,
                "tier": sig.get("tier", "UNKNOWN"),
                "confidence": sig.get("confidence", 0),
            })

        total_signals = len(signals)
        signals_traded = len(traded_signals)
        accuracy = correct / signals_traded if signals_traded > 0 else 0

        return {
            "total_signals": total_signals,
            "signals_traded": signals_traded,
            "signals_skipped": total_signals - signals_traded,
            "accuracy": round(accuracy, 3),
            "correct": correct,
            "incorrect": signals_traded - correct,
            "details": details,
        }

    def get_execution_quality(self) -> Dict[str, Any]:
        """
        Measure execution quality vs signal levels.

        Tracks slippage from signal entry, whether exits were at TP/SL levels,
        and overall execution discipline.
        """
        signals = _load_sniper_signals()
        closed = self.journal.get_closed_trades()

        if not closed:
            return {
                "total_trades": 0,
                "avg_slippage_pct": 0,
                "trades_with_signal": 0,
                "tp_exits": 0,
                "sl_exits": 0,
                "manual_exits": 0,
            }

        slippages = []
        tp_exits = 0
        sl_exits = 0
        manual_exits = 0
        trades_with_signal = 0

        for trade in closed:
            reason = (trade.exit_reason or "").upper()
            if "TP" in reason:
                tp_exits += 1
            elif "SL" in reason:
                sl_exits += 1
            else:
                manual_exits += 1

            # Find matching signal for slippage
            for sig in signals:
                if sig.get("symbol") == trade.symbol and sig.get("side") == trade.side:
                    sig_entry = sig.get("entry", 0)
                    if sig_entry > 0:
                        slip = abs(trade.entry_price - sig_entry) / sig_entry * 100
                        slippages.append(slip)
                        trades_with_signal += 1
                    break

        return {
            "total_trades": len(closed),
            "avg_slippage_pct": round(sum(slippages) / len(slippages), 3) if slippages else 0,
            "max_slippage_pct": round(max(slippages), 3) if slippages else 0,
            "trades_with_signal": trades_with_signal,
            "tp_exits": tp_exits,
            "sl_exits": sl_exits,
            "manual_exits": manual_exits,
            "discipline_score": round(
                (tp_exits + sl_exits) / len(closed) * 100, 1
            ) if closed else 0,
        }

    def get_system_grade(self) -> Dict[str, Any]:
        """
        Grade the entire sniper signal system.

        Answers: if you followed every signal exactly, what would your results be?
        """
        signals = _load_sniper_signals()
        if not signals:
            return {
                "total_signals": 0,
                "grade": "N/A",
                "description": "No signals generated yet",
            }

        # Group by tier
        by_tier: Dict[str, List] = defaultdict(list)
        for sig in signals:
            tier = sig.get("tier", "UNKNOWN")
            by_tier[tier].append(sig)

        # Calculate theoretical performance using actual trade outcomes
        closed = self.journal.get_closed_trades()
        total_pnl = sum(t.pnl for t in closed if t.pnl is not None)
        win_count = sum(1 for t in closed if t.pnl is not None and t.pnl > 0)
        loss_count = sum(1 for t in closed if t.pnl is not None and t.pnl <= 0)

        win_rate = win_count / (win_count + loss_count) if (win_count + loss_count) > 0 else 0

        # Grade based on performance
        if win_rate >= 0.7 and total_pnl > 0:
            grade = "A"
            desc = "Excellent system edge. Keep executing."
        elif win_rate >= 0.55 and total_pnl > 0:
            grade = "B"
            desc = "Good edge. Room for improvement on entry timing."
        elif total_pnl > 0:
            grade = "C"
            desc = "Marginal edge. Tighten filters or improve execution."
        elif total_pnl == 0:
            grade = "D"
            desc = "Breakeven. Need more data or better signals."
        else:
            grade = "F"
            desc = "Losing money. Review signal quality and execution."

        tier_stats = {}
        for tier, sigs in by_tier.items():
            tier_stats[tier] = {
                "count": len(sigs),
                "avg_confidence": round(
                    sum(s.get("confidence", 0) for s in sigs) / len(sigs), 1
                ) if sigs else 0,
            }

        return {
            "total_signals": len(signals),
            "total_trades": len(closed),
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "grade": grade,
            "description": desc,
            "by_tier": tier_stats,
        }

    def get_daily_pnl(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get daily P&L breakdown for the last N days.

        Returns list of {date, pnl, trades, wins, losses} per day.
        """
        closed = self.journal.get_closed_trades()
        if not closed:
            return []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        daily: Dict[str, Dict] = defaultdict(lambda: {
            "pnl": 0, "trades": 0, "wins": 0, "losses": 0
        })

        for trade in closed:
            if not trade.exit_time:
                continue
            exit_time = datetime.fromisoformat(trade.exit_time)
            if exit_time < cutoff:
                continue
            day_key = exit_time.strftime("%Y-%m-%d")
            d = daily[day_key]
            d["trades"] += 1
            if trade.pnl is not None:
                d["pnl"] += trade.pnl
                if trade.pnl > 0:
                    d["wins"] += 1
                else:
                    d["losses"] += 1

        result = []
        for day_key in sorted(daily.keys()):
            d = daily[day_key]
            result.append({
                "date": day_key,
                "pnl": round(d["pnl"], 2),
                "trades": d["trades"],
                "wins": d["wins"],
                "losses": d["losses"],
                "win_rate": round(d["wins"] / d["trades"], 2) if d["trades"] > 0 else 0,
            })

        return result

    def get_weekly_pnl(self, weeks: int = 4) -> List[Dict[str, Any]]:
        """
        Get weekly P&L breakdown for the last N weeks.
        """
        closed = self.journal.get_closed_trades()
        if not closed:
            return []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(weeks=weeks)

        weekly: Dict[str, Dict] = defaultdict(lambda: {
            "pnl": 0, "trades": 0, "wins": 0, "losses": 0
        })

        for trade in closed:
            if not trade.exit_time:
                continue
            exit_time = datetime.fromisoformat(trade.exit_time)
            if exit_time < cutoff:
                continue
            # ISO week key
            week_key = exit_time.strftime("%Y-W%W")
            w = weekly[week_key]
            w["trades"] += 1
            if trade.pnl is not None:
                w["pnl"] += trade.pnl
                if trade.pnl > 0:
                    w["wins"] += 1
                else:
                    w["losses"] += 1

        result = []
        for week_key in sorted(weekly.keys()):
            w = weekly[week_key]
            result.append({
                "week": week_key,
                "pnl": round(w["pnl"], 2),
                "trades": w["trades"],
                "wins": w["wins"],
                "losses": w["losses"],
                "win_rate": round(w["wins"] / w["trades"], 2) if w["trades"] > 0 else 0,
            })

        return result

    def format_performance_report(self) -> str:
        """Format a comprehensive performance report for Telegram."""
        stats = self.journal.get_stats()
        grade = self.get_system_grade()
        quality = self.get_execution_quality()

        lines = [
            "=" * 30,
            "  PERFORMANCE REPORT",
            "=" * 30,
            "",
            f"Trades: {stats['total_trades']} closed, {stats.get('open_trades', 0)} open",
            f"Win Rate: {stats['win_rate']:.0%} ({stats.get('wins', 0)}W / {stats.get('losses', 0)}L)",
            f"Profit Factor: {stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "Profit Factor: INF (no losses)",
            f"Total PnL: ${stats['total_pnl']:+,.2f}",
            f"Best Trade: ${stats['best_trade']:+,.2f}",
            f"Worst Trade: ${stats['worst_trade']:+,.2f}",
            f"Avg PnL: ${stats['avg_pnl']:+,.2f}",
            f"Avg Hold: {stats['avg_hold_hours']:.1f}h",
            "",
            f"System Grade: {grade['grade']} — {grade['description']}",
            "",
            f"Execution Quality:",
            f"  Avg Slippage: {quality['avg_slippage_pct']:.3f}%",
            f"  TP Exits: {quality['tp_exits']} | SL Exits: {quality['sl_exits']} | Manual: {quality['manual_exits']}",
            f"  Discipline: {quality['discipline_score']:.0f}%",
            "=" * 30,
        ]

        return "\n".join(lines)
