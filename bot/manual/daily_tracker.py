"""
Daily P&L Tracker for the $100 Sniper Account.

Reads from sim_trades.jsonl and trade_journal.jsonl, calculates daily P&L,
running equity, win rate per day, and projects milestones ($250, $500, $1000).

Flags risk events (daily loss > 15%) for reduced sizing the next day.
"""

import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("bot.manual.daily_tracker")

_DATA_DIR = os.path.join("data", "manual")
_SIM_TRADES_PATH = os.path.join(_DATA_DIR, "sim_trades.jsonl")
_JOURNAL_PATH = os.path.join(_DATA_DIR, "trade_journal.jsonl")
_EQUITY_STATE_PATH = os.path.join(_DATA_DIR, "equity_state.json")

STARTING_EQUITY = 100.0
TARGET_EQUITY = 1000.0
MILESTONES = [250.0, 500.0, 1000.0]
DAILY_LOSS_THRESHOLD = 0.15  # 15% daily loss triggers reduced sizing flag


@dataclass
class DayStats:
    """Statistics for a single trading day."""
    date: str
    starting_equity: float
    ending_equity: float
    pnl: float
    pnl_pct: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    reduced_sizing_flag: bool = False


class DailyTracker:
    """
    Tracks daily P&L and compounding progress for the $100 sniper account.

    Reads closed trades from both sim_trades.jsonl (simulator) and
    trade_journal.jsonl (manual journal), aggregates by day, and
    computes growth projections toward the $1,000 target.
    """

    def __init__(
        self,
        sim_trades_path: str = _SIM_TRADES_PATH,
        journal_path: str = _JOURNAL_PATH,
        equity_state_path: str = _EQUITY_STATE_PATH,
        starting_equity: float = STARTING_EQUITY,
        target_equity: float = TARGET_EQUITY,
    ):
        self.sim_trades_path = sim_trades_path
        self.journal_path = journal_path
        self.equity_state_path = equity_state_path
        self.starting_equity = starting_equity
        self.target_equity = target_equity
        self._trades: List[Dict[str, Any]] = []
        self._day_stats: List[DayStats] = []

        self._load_trades()
        self._compute_daily_stats()

    def _load_trades(self) -> None:
        """Load closed trades from both sim_trades.jsonl and trade_journal.jsonl."""
        self._trades = []

        # Load simulator trades
        self._trades.extend(self._read_jsonl(self.sim_trades_path, source="sim"))

        # Load manual journal trades (closed only)
        for t in self._read_jsonl(self.journal_path, source="journal"):
            if t.get("status") == "CLOSED":
                self._trades.append(t)

        # Sort by close time
        self._trades.sort(key=lambda t: self._get_close_time(t))

    def _read_jsonl(self, path: str, source: str = "") -> List[Dict[str, Any]]:
        """Read a JSONL file, returning list of dicts. Skips corrupt lines."""
        results = []
        if not os.path.exists(path):
            return results
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        d["_source"] = source
                        results.append(d)
                    except (json.JSONDecodeError, TypeError):
                        continue
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
        return results

    def _get_close_time(self, trade: Dict[str, Any]) -> str:
        """Extract close timestamp from a trade dict (handles both formats)."""
        return trade.get("closed_at") or trade.get("exit_time") or ""

    def _get_pnl(self, trade: Dict[str, Any]) -> float:
        """Extract P&L from a trade dict (handles both formats)."""
        return trade.get("pnl_usd") or trade.get("pnl") or 0.0

    def _is_win(self, trade: Dict[str, Any]) -> bool:
        """Determine if a trade was a win."""
        result = trade.get("result", "")
        if result:
            return result == "WIN"
        return self._get_pnl(trade) > 0

    def _compute_daily_stats(self) -> None:
        """Aggregate trades by day and compute per-day statistics."""
        self._day_stats = []

        if not self._trades:
            return

        # Group trades by close date
        daily_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for trade in self._trades:
            close_time = self._get_close_time(trade)
            if not close_time:
                continue
            day_key = close_time[:10]  # YYYY-MM-DD
            daily_trades[day_key].append(trade)

        # Sort days chronologically
        sorted_days = sorted(daily_trades.keys())

        running_equity = self.starting_equity

        for day_key in sorted_days:
            trades = daily_trades[day_key]
            day_start_equity = running_equity

            day_pnl = 0.0
            wins = 0
            losses = 0

            for trade in trades:
                pnl = self._get_pnl(trade)
                day_pnl += pnl
                if self._is_win(trade):
                    wins += 1
                else:
                    losses += 1

            running_equity += day_pnl
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
            pnl_pct = (day_pnl / day_start_equity * 100) if day_start_equity > 0 else 0.0

            # Flag if daily loss exceeds threshold
            reduced_flag = pnl_pct < -(DAILY_LOSS_THRESHOLD * 100)

            self._day_stats.append(DayStats(
                date=day_key,
                starting_equity=round(day_start_equity, 2),
                ending_equity=round(running_equity, 2),
                pnl=round(day_pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                trades=total_trades,
                wins=wins,
                losses=losses,
                win_rate=round(win_rate, 1),
                reduced_sizing_flag=reduced_flag,
            ))

    @property
    def current_equity(self) -> float:
        """Current equity after all tracked trades."""
        if self._day_stats:
            return self._day_stats[-1].ending_equity
        return self.starting_equity

    @property
    def days_traded(self) -> int:
        """Number of days with at least one trade."""
        return len(self._day_stats)

    def get_daily_stats(self) -> List[DayStats]:
        """Return per-day stats list."""
        return list(self._day_stats)

    def get_best_day(self) -> Optional[DayStats]:
        """Day with highest P&L."""
        if not self._day_stats:
            return None
        return max(self._day_stats, key=lambda d: d.pnl)

    def get_worst_day(self) -> Optional[DayStats]:
        """Day with lowest P&L."""
        if not self._day_stats:
            return None
        return min(self._day_stats, key=lambda d: d.pnl)

    def get_avg_daily_return_pct(self) -> float:
        """Average daily return percentage across all trading days."""
        if not self._day_stats:
            return 0.0
        return sum(d.pnl_pct for d in self._day_stats) / len(self._day_stats)

    def get_streak(self) -> Tuple[int, str]:
        """
        Current streak: consecutive winning or losing days.
        Returns (count, "win"|"loss"|"none").
        """
        if not self._day_stats:
            return (0, "none")

        streak = 0
        streak_type = "none"

        for day in reversed(self._day_stats):
            if day.pnl > 0:
                if streak_type == "none":
                    streak_type = "win"
                if streak_type == "win":
                    streak += 1
                else:
                    break
            elif day.pnl < 0:
                if streak_type == "none":
                    streak_type = "loss"
                if streak_type == "loss":
                    streak += 1
                else:
                    break
            else:
                # Breakeven day - doesn't break streak but doesn't count
                break

        return (streak, streak_type)

    def get_compound_growth_rate(self) -> float:
        """
        Daily compound growth rate based on actual equity curve.
        Returns as a decimal (e.g., 0.05 = 5% per day).
        """
        if not self._day_stats or self.current_equity <= 0:
            return 0.0

        growth_ratio = self.current_equity / self.starting_equity
        if growth_ratio <= 0:
            return 0.0

        n_days = max(self.days_traded, 1)
        return growth_ratio ** (1.0 / n_days) - 1.0

    def project_milestones(self) -> Dict[float, Optional[int]]:
        """
        Project days to reach each milestone at current compound rate.
        Returns {milestone: days_from_now} or None if unreachable.
        """
        rate = self.get_compound_growth_rate()
        equity = self.current_equity
        projections: Dict[float, Optional[int]] = {}

        for milestone in MILESTONES:
            if equity >= milestone:
                projections[milestone] = 0
            elif rate > 0:
                try:
                    days = math.log(milestone / equity) / math.log(1.0 + rate)
                    projections[milestone] = round(days)
                except (ValueError, ZeroDivisionError):
                    projections[milestone] = None
            else:
                projections[milestone] = None

        return projections

    def should_reduce_sizing_today(self) -> bool:
        """
        Check if yesterday had a daily loss exceeding the threshold,
        meaning today should use reduced sizing.
        """
        if not self._day_stats:
            return False
        last_day = self._day_stats[-1]
        return last_day.reduced_sizing_flag

    def get_summary(self) -> Dict[str, Any]:
        """Full summary dict for programmatic consumption."""
        best = self.get_best_day()
        worst = self.get_worst_day()
        streak_count, streak_type = self.get_streak()
        milestones = self.project_milestones()
        rate = self.get_compound_growth_rate()

        total_trades = sum(d.trades for d in self._day_stats)
        total_wins = sum(d.wins for d in self._day_stats)
        overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
        progress_pct = 0.0
        if self.target_equity > self.starting_equity:
            progress_pct = (
                (self.current_equity - self.starting_equity)
                / (self.target_equity - self.starting_equity)
                * 100
            )

        return {
            "starting_equity": self.starting_equity,
            "current_equity": self.current_equity,
            "target_equity": self.target_equity,
            "progress_pct": round(max(0.0, min(progress_pct, 100.0)), 1),
            "days_traded": self.days_traded,
            "total_trades": total_trades,
            "total_wins": total_wins,
            "overall_win_rate": round(overall_wr, 1),
            "avg_daily_return_pct": round(self.get_avg_daily_return_pct(), 2),
            "compound_growth_rate_pct": round(rate * 100, 2),
            "best_day_pnl": best.pnl if best else 0,
            "best_day_pct": best.pnl_pct if best else 0,
            "best_day_date": best.date if best else None,
            "worst_day_pnl": worst.pnl if worst else 0,
            "worst_day_pct": worst.pnl_pct if worst else 0,
            "worst_day_date": worst.date if worst else None,
            "streak_count": streak_count,
            "streak_type": streak_type,
            "milestone_projections": {
                f"${int(m)}": f"{d} days" if d is not None and d > 0
                else "REACHED" if d == 0
                else "N/A"
                for m, d in milestones.items()
            },
            "reduce_sizing_today": self.should_reduce_sizing_today(),
        }


def format_daily_dashboard(tracker: Optional[DailyTracker] = None) -> str:
    """
    Format a Telegram-ready daily dashboard showing $100 account progress.

    Args:
        tracker: DailyTracker instance. If None, creates a fresh one.

    Returns:
        Formatted string suitable for Telegram message.
    """
    if tracker is None:
        tracker = DailyTracker()

    summary = tracker.get_summary()
    lines: List[str] = []

    # Header
    lines.append("=== $100 ACCOUNT TRACKER ===")
    lines.append("")

    # Equity curve (show last 10 days)
    day_stats = tracker.get_daily_stats()
    if day_stats:
        display_days = day_stats[-10:]
        for i, day in enumerate(display_days):
            day_num = day_stats.index(day) + 1
            pnl_sign = "+" if day.pnl >= 0 else ""
            pct_sign = "+" if day.pnl_pct >= 0 else ""
            flag = " [!]" if day.reduced_sizing_flag else ""
            lines.append(
                f"Day {day_num} | ${day.starting_equity:.0f} -> "
                f"${day.ending_equity:.0f} ({pct_sign}{day.pnl_pct:.1f}%) "
                f"W:{day.wins} L:{day.losses}{flag}"
            )
        if len(day_stats) > 10:
            lines.insert(2, f"  ... ({len(day_stats) - 10} earlier days)")
        lines.append("")
    else:
        lines.append("No trades yet. Waiting for first signal...")
        lines.append("")

    # Current equity and progress bar
    current = summary["current_equity"]
    target = summary["target_equity"]
    progress = summary["progress_pct"]
    filled = int(progress / 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    lines.append(f"Current: ${current:.2f} | Target: ${target:,.0f}")
    lines.append(f"Progress: [{bar}] {progress:.1f}%")
    lines.append("")

    # Key stats
    avg_daily = summary["avg_daily_return_pct"]
    best_pct = summary["best_day_pct"]
    worst_pct = summary["worst_day_pct"]
    lines.append(
        f"Avg daily: {'+' if avg_daily >= 0 else ''}{avg_daily:.1f}% | "
        f"Best: +{best_pct:.1f}% | "
        f"Worst: {worst_pct:.1f}%"
    )

    # Win rate and trades
    lines.append(
        f"Win rate: {summary['overall_win_rate']:.0f}% | "
        f"Trades: {summary['total_trades']} | "
        f"Days: {summary['days_traded']}"
    )

    # Streak
    streak_count = summary["streak_count"]
    streak_type = summary["streak_type"]
    if streak_count > 0:
        emoji = "W" if streak_type == "win" else "L"
        lines.append(f"Streak: {streak_count}{emoji}")

    lines.append("")

    # Milestone projections
    lines.append("-- Projections --")
    for milestone_label, projection in summary["milestone_projections"].items():
        lines.append(f"  {milestone_label}: {projection}")

    # Risk warning
    if summary["reduce_sizing_today"]:
        lines.append("")
        lines.append("[!] REDUCE SIZING: Yesterday exceeded 15% loss")

    return "\n".join(lines)
