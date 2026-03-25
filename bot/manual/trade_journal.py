"""
Manual Trade Journal & Equity Tracker.

Logs actual manual trade executions against sniper signals,
tracks running equity, and provides compounding progress reports.

Data stored in data/manual/trade_journal.jsonl (append-only).
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("bot.manual.trade_journal")

_JOURNAL_DIR = os.path.join("data", "manual")
_JOURNAL_FILE = os.path.join(_JOURNAL_DIR, "trade_journal.jsonl")
_EQUITY_FILE = os.path.join(_JOURNAL_DIR, "equity_state.json")

STARTING_EQUITY = 100.0


@dataclass
class JournalEntry:
    """A single trade entry in the journal."""
    trade_id: str
    symbol: str
    side: str               # BUY or SELL
    entry_price: float
    leverage: float
    qty: float              # Asset quantity
    margin_used: float      # Actual margin (entry_price * qty / leverage)
    signal_id: Optional[str] = None  # Link to sniper signal if applicable

    # Exit fields (filled on close)
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # TP, SL, MANUAL, BREAKEVEN
    exit_time: Optional[str] = None

    # Computed on exit
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None       # % return on margin
    hold_time_hours: Optional[float] = None

    # Metadata
    entry_time: str = ""
    status: str = "OPEN"    # OPEN or CLOSED
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JournalEntry":
        return JournalEntry(**{k: v for k, v in d.items() if k in JournalEntry.__dataclass_fields__})


class TradeJournal:
    """
    Manages a JSONL trade journal for manual trades.

    Tracks entries, exits, running equity, and compounding progress.
    Optionally links trades to sniper signals for performance comparison.
    """

    def __init__(
        self,
        journal_path: str = _JOURNAL_FILE,
        equity_path: str = _EQUITY_FILE,
        starting_equity: float = STARTING_EQUITY,
    ):
        self.journal_path = journal_path
        self.equity_path = equity_path
        self.starting_equity = starting_equity
        self._trades: List[JournalEntry] = []
        self._current_equity: float = starting_equity
        self._start_date: Optional[str] = None

        os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)
        self._load()

    def _load(self):
        """Load existing journal entries and equity state."""
        # Load trades
        if os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                d = json.loads(line)
                                self._trades.append(JournalEntry.from_dict(d))
                            except (json.JSONDecodeError, TypeError):
                                continue
            except Exception as e:
                logger.warning(f"Failed to load journal: {e}")

        # Load equity state
        if os.path.exists(self.equity_path):
            try:
                with open(self.equity_path, "r") as f:
                    state = json.load(f)
                    self._current_equity = state.get("current_equity", self.starting_equity)
                    self._start_date = state.get("start_date")
                    self.starting_equity = state.get("starting_equity", self.starting_equity)
            except Exception as e:
                logger.warning(f"Failed to load equity state: {e}")

        if not self._start_date:
            self._start_date = datetime.now(timezone.utc).isoformat()

    def _save_equity_state(self):
        """Persist current equity state atomically."""
        tmp_path = self.equity_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump({
                    "current_equity": round(self._current_equity, 2),
                    "starting_equity": self.starting_equity,
                    "start_date": self._start_date,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)
            os.replace(tmp_path, self.equity_path)
        except Exception as e:
            logger.warning(f"Failed to save equity state: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _append_trade(self, entry: JournalEntry):
        """Append a trade entry to the JSONL file."""
        try:
            with open(self.journal_path, "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"Failed to append journal entry: {e}")

    def _rewrite_journal(self):
        """Rewrite full journal atomically (write to tmp, then rename)."""
        tmp_path = self.journal_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                for trade in self._trades:
                    f.write(json.dumps(trade.to_dict()) + "\n")
            os.replace(tmp_path, self.journal_path)
        except Exception as e:
            logger.warning(f"Failed to rewrite journal: {e}")
            # Clean up tmp file on failure
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ── Public API ──

    def log_entry(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        leverage: float,
        qty: float,
        signal_id: Optional[str] = None,
        notes: str = "",
    ) -> JournalEntry:
        """
        Log a new manual trade entry.

        Args:
            symbol: Trading pair (e.g., HYPE, BTC, SOL)
            side: BUY or SELL
            entry_price: Actual entry price
            leverage: Leverage used (e.g., 25)
            qty: Asset quantity purchased
            signal_id: Optional sniper signal ID this trade is based on
            notes: Optional notes

        Returns:
            JournalEntry with generated trade_id
        """
        symbol = symbol.upper().strip()
        side = side.upper().strip()
        if side not in ("BUY", "SELL", "LONG", "SHORT"):
            raise ValueError(f"Invalid side: {side}. Use BUY/SELL or LONG/SHORT")
        if side == "LONG":
            side = "BUY"
        elif side == "SHORT":
            side = "SELL"

        position_value = entry_price * qty
        margin_used = position_value / leverage if leverage > 0 else position_value

        trade_id = f"MJ-{uuid.uuid4().hex[:8].upper()}"

        entry = JournalEntry(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            leverage=leverage,
            qty=qty,
            margin_used=round(margin_used, 2),
            signal_id=signal_id,
            entry_time=datetime.now(timezone.utc).isoformat(),
            status="OPEN",
            notes=notes,
        )

        self._trades.append(entry)
        self._append_trade(entry)
        logger.info(
            f"[JOURNAL] ENTRY {trade_id}: {symbol} {side} @ {entry_price} "
            f"{leverage}x qty={qty} margin=${margin_used:.2f}"
        )
        return entry

    def log_exit(
        self,
        trade_id_or_symbol: str,
        exit_price: float,
        reason: str = "MANUAL",
        notes: str = "",
    ) -> Optional[JournalEntry]:
        """
        Log a trade exit. Finds trade by ID or symbol (most recent open).

        Args:
            trade_id_or_symbol: Trade ID (MJ-XXXX) or symbol name
            exit_price: Actual exit price
            reason: TP, SL, MANUAL, BREAKEVEN
            notes: Optional notes

        Returns:
            Updated JournalEntry or None if not found
        """
        trade = self._find_open_trade(trade_id_or_symbol)
        if not trade:
            logger.warning(f"[JOURNAL] No open trade found for: {trade_id_or_symbol}")
            return None

        now = datetime.now(timezone.utc)
        entry_time = datetime.fromisoformat(trade.entry_time)
        hold_hours = (now - entry_time).total_seconds() / 3600

        # Calculate PnL with leverage
        if trade.side == "BUY":
            price_change_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            price_change_pct = (trade.entry_price - exit_price) / trade.entry_price

        position_value = trade.entry_price * trade.qty
        pnl = position_value * price_change_pct
        pnl_pct = price_change_pct * trade.leverage * 100  # % return on margin

        # Update trade
        trade.exit_price = exit_price
        trade.exit_reason = reason.upper()
        trade.exit_time = now.isoformat()
        trade.pnl = round(pnl, 2)
        trade.pnl_pct = round(pnl_pct, 2)
        trade.hold_time_hours = round(hold_hours, 2)
        trade.status = "CLOSED"
        if notes:
            trade.notes = (trade.notes + " | " + notes).strip(" | ")

        # Update equity
        self._current_equity += pnl
        self._current_equity = round(self._current_equity, 2)

        self._rewrite_journal()
        self._save_equity_state()

        logger.info(
            f"[JOURNAL] EXIT {trade.trade_id}: {trade.symbol} @ {exit_price} "
            f"reason={reason} PnL=${pnl:+.2f} ({pnl_pct:+.1f}%) "
            f"hold={hold_hours:.1f}h equity=${self._current_equity:.2f}"
        )
        return trade

    def _find_open_trade(self, trade_id_or_symbol: str) -> Optional[JournalEntry]:
        """Find an open trade by ID or symbol (most recent open)."""
        needle = trade_id_or_symbol.upper().strip()

        # Try exact trade ID match first
        for trade in self._trades:
            if trade.trade_id == needle and trade.status == "OPEN":
                return trade

        # Try symbol match (most recent open)
        for trade in reversed(self._trades):
            if trade.symbol == needle and trade.status == "OPEN":
                return trade

        return None

    def get_open_trades(self) -> List[JournalEntry]:
        """Get all currently open trades."""
        return [t for t in self._trades if t.status == "OPEN"]

    def get_closed_trades(self) -> List[JournalEntry]:
        """Get all closed trades."""
        return [t for t in self._trades if t.status == "CLOSED"]

    def get_recent_trades(self, n: int = 10) -> List[JournalEntry]:
        """Get N most recent trades (open and closed)."""
        return self._trades[-n:]

    @property
    def current_equity(self) -> float:
        return self._current_equity

    def set_equity(self, equity: float):
        """Manually set current equity (for corrections)."""
        self._current_equity = round(equity, 2)
        self._save_equity_state()

    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """
        Build equity curve from trade history.

        Returns list of {time, equity, trade_id, pnl} points.
        """
        curve = [{
            "time": self._start_date,
            "equity": self.starting_equity,
            "trade_id": None,
            "pnl": 0,
        }]
        running = self.starting_equity
        for trade in self._trades:
            if trade.status == "CLOSED" and trade.pnl is not None:
                running += trade.pnl
                curve.append({
                    "time": trade.exit_time,
                    "equity": round(running, 2),
                    "trade_id": trade.trade_id,
                    "pnl": trade.pnl,
                })
        return curve

    def get_stats(self) -> Dict[str, Any]:
        """
        Compute overall trading statistics.

        Returns:
            Dict with total_trades, win_rate, profit_factor, total_pnl,
            current_equity, best_trade, worst_trade, avg_hold_hours, etc.
        """
        closed = self.get_closed_trades()
        if not closed:
            return {
                "total_trades": 0,
                "open_trades": len(self.get_open_trades()),
                "win_rate": 0,
                "profit_factor": 0,
                "total_pnl": 0,
                "current_equity": self._current_equity,
                "starting_equity": self.starting_equity,
                "best_trade": 0,
                "worst_trade": 0,
                "avg_hold_hours": 0,
                "avg_pnl": 0,
                "total_return_pct": 0,
            }

        wins = [t for t in closed if t.pnl is not None and t.pnl > 0]
        losses = [t for t in closed if t.pnl is not None and t.pnl <= 0]

        total_wins = sum(t.pnl for t in wins)
        total_losses = abs(sum(t.pnl for t in losses))
        total_pnl = sum(t.pnl for t in closed if t.pnl is not None)

        pnl_values = [t.pnl for t in closed if t.pnl is not None]
        hold_times = [t.hold_time_hours for t in closed if t.hold_time_hours is not None]

        return {
            "total_trades": len(closed),
            "open_trades": len(self.get_open_trades()),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) if closed else 0,
            "profit_factor": total_wins / total_losses if total_losses > 0 else float("inf") if total_wins > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "current_equity": self._current_equity,
            "starting_equity": self.starting_equity,
            "best_trade": round(max(pnl_values), 2) if pnl_values else 0,
            "worst_trade": round(min(pnl_values), 2) if pnl_values else 0,
            "avg_pnl": round(total_pnl / len(closed), 2) if closed else 0,
            "avg_hold_hours": round(sum(hold_times) / len(hold_times), 1) if hold_times else 0,
            "total_return_pct": round((self._current_equity - self.starting_equity) / self.starting_equity * 100, 2),
            "longest_win_streak": self._longest_streak(closed, winning=True),
            "longest_loss_streak": self._longest_streak(closed, winning=False),
        }

    def _longest_streak(self, trades: List[JournalEntry], winning: bool) -> int:
        """Count longest consecutive win or loss streak."""
        max_streak = 0
        current = 0
        for t in trades:
            if t.pnl is None:
                continue
            is_win = t.pnl > 0
            if is_win == winning:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def get_compounding_report(self) -> Dict[str, Any]:
        """
        Generate compounding progress report.

        Tracks progress from starting equity toward $1000 target,
        with daily growth rate and projection.
        """
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(self._start_date)
        days_elapsed = max((now - start).total_seconds() / 86400, 0.01)  # Avoid div by zero

        total_return = self._current_equity - self.starting_equity
        total_return_pct = (total_return / self.starting_equity * 100) if self.starting_equity > 0 else 0

        # Daily average growth rate (compound)
        if self._current_equity > 0 and self.starting_equity > 0:
            growth_ratio = self._current_equity / self.starting_equity
            if growth_ratio > 0:
                daily_compound_rate = (growth_ratio ** (1 / days_elapsed) - 1)
            else:
                daily_compound_rate = 0
        else:
            daily_compound_rate = 0

        # Projection to $1000
        target = 1000.0
        if daily_compound_rate > 0 and self._current_equity < target:
            import math
            days_to_target = math.log(target / self._current_equity) / math.log(1 + daily_compound_rate)
            projected_date = now + timedelta(days=days_to_target)
        elif self._current_equity >= target:
            days_to_target = 0
            projected_date = now
        else:
            days_to_target = float("inf")
            projected_date = None

        # Weekly equity projections
        projections = {}
        for weeks in [1, 2, 4, 8, 12]:
            if daily_compound_rate > 0:
                try:
                    proj = self._current_equity * ((1 + daily_compound_rate) ** (weeks * 7))
                    if proj > 1e12:  # Cap at $1 trillion for sanity
                        proj = 1e12
                    projections[f"{weeks}w"] = round(proj, 2)
                except (OverflowError, ValueError):
                    projections[f"{weeks}w"] = self._current_equity
            else:
                projections[f"{weeks}w"] = self._current_equity

        closed = self.get_closed_trades()
        trades_per_day = len(closed) / days_elapsed if days_elapsed > 0 else 0

        return {
            "starting_equity": self.starting_equity,
            "current_equity": self._current_equity,
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "days_elapsed": round(days_elapsed, 1),
            "daily_compound_rate_pct": round(daily_compound_rate * 100, 3),
            "trades_per_day": round(trades_per_day, 1),
            "target": target,
            "days_to_target": round(days_to_target, 1) if days_to_target != float("inf") else None,
            "projected_target_date": projected_date.strftime("%Y-%m-%d") if projected_date else None,
            "projections": projections,
            "progress_pct": round(
                (self._current_equity - self.starting_equity) / (target - self.starting_equity) * 100, 1
            ) if target > self.starting_equity else 100.0,
        }


# ── Module-level singleton ──

_journal_instance: Optional[TradeJournal] = None


def get_trade_journal() -> TradeJournal:
    """Get or create the global TradeJournal instance."""
    global _journal_instance
    if _journal_instance is None:
        _journal_instance = TradeJournal()
    return _journal_instance
