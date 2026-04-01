"""
Per-Wallet P&L Tracker — separate equity curves and trade logs per wallet.

Mirrors the SniperSimulator equity tracking pattern: each wallet maintains
its own equity, trade history, and daily P&L. The tracker is append-only
for trade logs and periodically snapshots equity state.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.wallet.pnl_tracker")


@dataclass
class WalletTrade:
    """Record of a closed trade attributed to a specific wallet."""
    trade_id: str
    wallet_id: str
    symbol: str
    side: str
    entry: float
    exit_price: float
    qty: float
    leverage: float
    pnl: float
    fees: float
    net_pnl: float
    hold_time_s: float
    outcome: str           # CLEAN_WIN, CLEAN_LOSS, TP1_ONLY, etc.
    signal_source: str     # anticipatory, candle_pattern, etc.
    scorecard_score: int
    opened_at: str
    closed_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class WalletPnLTracker:
    """Tracks P&L for a single wallet independently."""

    def __init__(self, wallet_id: str, starting_equity: float, data_dir: str = "data"):
        self.wallet_id = wallet_id
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.peak_equity = starting_equity

        # Stats
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.max_drawdown = 0.0
        self._last_reset_date: Optional[str] = None

        # Persistence paths
        self._data_dir = os.path.join(data_dir, f"wallet_{wallet_id.lower()}")
        self._trades_path = os.path.join(self._data_dir, "trades.jsonl")
        self._status_path = os.path.join(self._data_dir, "status.json")

        os.makedirs(self._data_dir, exist_ok=True)
        self._load_state()

    def _load_state(self):
        """Load persisted state if available."""
        if os.path.exists(self._status_path):
            try:
                with open(self._status_path, 'r') as f:
                    state = json.load(f)
                self.equity = state.get('equity', self.starting_equity)
                self.peak_equity = state.get('peak_equity', self.equity)
                self.total_trades = state.get('total_trades', 0)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.total_pnl = state.get('total_pnl', 0.0)
                self.max_drawdown = state.get('max_drawdown', 0.0)
                logger.info(
                    f"Wallet {self.wallet_id} state loaded: "
                    f"equity=${self.equity:.2f}, {self.total_trades} trades"
                )
            except Exception as e:
                logger.warning(f"Failed to load wallet {self.wallet_id} state: {e}")

    def _save_state(self):
        """Persist current state."""
        state = {
            'wallet_id': self.wallet_id,
            'equity': self.equity,
            'peak_equity': self.peak_equity,
            'starting_equity': self.starting_equity,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'total_pnl': self.total_pnl,
            'daily_pnl': self.daily_pnl,
            'max_drawdown': self.max_drawdown,
            'win_rate': self.win_rate,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._status_path, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save wallet {self.wallet_id} state: {e}")

    def record_trade(self, trade: WalletTrade):
        """Record a completed trade and update equity."""
        self.total_trades += 1
        self.total_pnl += trade.net_pnl
        self.equity += trade.net_pnl
        self.daily_pnl += trade.net_pnl

        if trade.net_pnl > 0:
            self.wins += 1
        else:
            self.losses += 1

        # Track peak and drawdown
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0
        if dd > self.max_drawdown:
            self.max_drawdown = dd

        # Append to trade log
        try:
            with open(self._trades_path, 'a') as f:
                f.write(json.dumps(trade.to_dict()) + '\n')
        except Exception as e:
            logger.warning(f"Failed to log wallet {self.wallet_id} trade: {e}")

        self._save_state()

        logger.info(
            f"[W{self.wallet_id}] Trade #{self.total_trades}: "
            f"{trade.symbol} {trade.side} PnL=${trade.net_pnl:+.2f} "
            f"Equity=${self.equity:.2f} WR={self.win_rate:.0f}%"
        )

    def reset_daily(self):
        """Reset daily P&L (call at start of each trading day)."""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if self._last_reset_date != today:
            self.daily_pnl = 0.0
            self._last_reset_date = today
            self._save_state()

    @property
    def win_rate(self) -> float:
        """Win rate as percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.wins / self.total_trades) * 100

    @property
    def pnl_pct(self) -> float:
        """Total P&L as percentage of starting equity."""
        if self.starting_equity <= 0:
            return 0.0
        return (self.total_pnl / self.starting_equity) * 100

    def get_summary(self) -> dict:
        """Get wallet performance summary."""
        return {
            'wallet_id': self.wallet_id,
            'equity': round(self.equity, 2),
            'starting_equity': round(self.starting_equity, 2),
            'total_pnl': round(self.total_pnl, 2),
            'pnl_pct': round(self.pnl_pct, 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': round(self.win_rate, 1),
            'max_drawdown_pct': round(self.max_drawdown * 100, 2),
        }
