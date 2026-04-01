"""
Wallet Context — bundles all per-wallet components into a single object.

Each wallet gets its own PositionManager, RiskManager, CircuitBreaker,
and PnL tracker. The WalletContext is the single handle passed around
for per-wallet operations.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from wallet.profile import WalletProfile
from wallet.pnl_tracker import WalletPnLTracker

logger = logging.getLogger("bot.wallet.context")


@dataclass
class WalletContext:
    """Everything a wallet needs to operate independently."""

    profile: WalletProfile

    # These are set after construction (injected by MultiStrategyBot)
    pos_mgr: Any = None           # PositionManager instance
    risk_mgr: Any = None          # RiskManager instance
    circuit_breaker: Any = None   # CircuitBreaker instance
    leverage_mgr: Any = None      # LeverageManager instance
    pnl_tracker: Optional[WalletPnLTracker] = None

    # Runtime state
    _initialized: bool = False

    @property
    def wallet_id(self) -> str:
        return self.profile.wallet_id

    @property
    def name(self) -> str:
        return self.profile.name

    def position_key(self, symbol: str) -> str:
        """Wallet-scoped position key."""
        return self.profile.position_key(symbol)

    def wallet_equity(self, total_equity: float) -> float:
        """This wallet's share of equity."""
        return self.profile.wallet_equity(total_equity)

    def get_open_count(self) -> int:
        """Number of open positions in this wallet."""
        if self.pos_mgr is None:
            return 0
        return len([
            p for p in self.pos_mgr.positions.values()
            if hasattr(p, 'state') and p.state not in ('CLOSED', 'IDLE')
        ])

    def get_open_notional(self) -> float:
        """Total notional value of open positions in this wallet."""
        if self.pos_mgr is None:
            return 0.0
        total = 0.0
        for p in self.pos_mgr.positions.values():
            if hasattr(p, 'state') and p.state not in ('CLOSED', 'IDLE'):
                total += abs(p.qty * p.entry * p.leverage)
        return total

    def can_open_position(self) -> bool:
        """Check if wallet has room for another position."""
        return self.get_open_count() < self.profile.max_open_positions

    def is_initialized(self) -> bool:
        return self._initialized and self.pos_mgr is not None

    def initialize(self):
        """Mark as ready after all components are injected."""
        if self.pos_mgr is None:
            raise ValueError(f"Wallet {self.wallet_id}: PositionManager not set")
        if self.risk_mgr is None:
            raise ValueError(f"Wallet {self.wallet_id}: RiskManager not set")
        if self.circuit_breaker is None:
            raise ValueError(f"Wallet {self.wallet_id}: CircuitBreaker not set")
        self._initialized = True
        logger.info(
            f"Wallet {self.wallet_id} ({self.name}) initialized: "
            f"max_lev={self.profile.max_leverage}x, "
            f"risk={self.profile.risk_per_trade*100:.1f}%, "
            f"max_pos={self.profile.max_open_positions}"
        )

    def __repr__(self) -> str:
        return (
            f"WalletContext(id={self.wallet_id}, name={self.name}, "
            f"positions={self.get_open_count()}/{self.profile.max_open_positions})"
        )
