"""
Wallet Profile — configuration for a single wallet within the dual-wallet system.

Wallet A (Conservative): anticipatory entries only, Half-Kelly 3.9x, high quality bar.
Wallet B (Aggressive): all signal sources, conviction-tiered 5-20x, more trades.
"""

import os
from dataclasses import dataclass, field
from typing import FrozenSet, Optional


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


# Signal source types that can be tagged on signals
SOURCE_ANTICIPATORY = "anticipatory"
SOURCE_CANDLE_PATTERN = "candle_pattern"
SOURCE_REGIME_PREDICTION = "regime_prediction"
SOURCE_ENSEMBLE = "ensemble"

ALL_SOURCES = frozenset({
    SOURCE_ANTICIPATORY,
    SOURCE_CANDLE_PATTERN,
    SOURCE_REGIME_PREDICTION,
    SOURCE_ENSEMBLE,
})

CONSERVATIVE_SOURCES = frozenset({SOURCE_ANTICIPATORY})


@dataclass(frozen=True)
class WalletProfile:
    """Immutable configuration for a single wallet."""

    wallet_id: str                          # "A" or "B"
    name: str                               # "Conservative" or "Aggressive"

    # Signal source filtering
    allowed_sources: FrozenSet[str] = ALL_SOURCES

    # Leverage
    max_leverage: float = 20.0
    leverage_mode: str = "conviction_tiered"  # "half_kelly" or "conviction_tiered"

    # Risk filters
    min_rr_ratio: float = 1.2
    min_scorecard: int = 50
    risk_per_trade: float = 0.005            # 0.5% default
    max_open_positions: int = 6

    # Equity allocation (fraction of total account equity)
    equity_pct: float = 0.5

    # Circuit breaker overrides
    cb_daily_loss_pct: float = 0.05
    cb_max_consecutive_losses: int = 5
    cb_max_drawdown_pct: float = 0.15

    # Alert routing
    telegram_chat_id: Optional[str] = None

    def position_key(self, symbol: str) -> str:
        """Wallet-scoped position key: 'WA:BTC' or 'WB:SOL'."""
        return f"W{self.wallet_id}:{symbol}"

    def accepts_source(self, source: str) -> bool:
        """Check if this wallet accepts the given signal source type."""
        return source in self.allowed_sources

    def wallet_equity(self, total_equity: float) -> float:
        """Calculate this wallet's share of total equity."""
        return total_equity * self.equity_pct


def wallet_a_default() -> WalletProfile:
    """Conservative wallet — anticipatory entries only, Half-Kelly 3.9x."""
    return WalletProfile(
        wallet_id=_env("WALLET_A_ID", "A"),
        name="Conservative",
        allowed_sources=CONSERVATIVE_SOURCES,
        max_leverage=_env_float("WALLET_A_MAX_LEVERAGE", 3.9),
        leverage_mode="half_kelly",
        min_rr_ratio=_env_float("WALLET_A_MIN_RR", 2.5),
        min_scorecard=_env_int("WALLET_A_MIN_SCORECARD", 70),
        risk_per_trade=_env_float("WALLET_A_RISK_PER_TRADE", 0.0035),
        max_open_positions=_env_int("WALLET_A_MAX_POSITIONS", 3),
        equity_pct=_env_float("WALLET_A_EQUITY_PCT", 0.5),
        cb_daily_loss_pct=_env_float("WALLET_A_CB_DAILY_LOSS", 0.03),
        cb_max_consecutive_losses=_env_int("WALLET_A_CB_MAX_CONSEC", 3),
        cb_max_drawdown_pct=_env_float("WALLET_A_CB_MAX_DD", 0.10),
        telegram_chat_id=os.getenv("WALLET_A_TELEGRAM_CHAT_ID"),
    )


def wallet_b_default() -> WalletProfile:
    """Aggressive wallet — all sources, conviction-tiered 5-20x."""
    return WalletProfile(
        wallet_id=_env("WALLET_B_ID", "B"),
        name="Aggressive",
        allowed_sources=ALL_SOURCES,
        max_leverage=_env_float("WALLET_B_MAX_LEVERAGE", 20.0),
        leverage_mode="conviction_tiered",
        min_rr_ratio=_env_float("WALLET_B_MIN_RR", 1.2),
        min_scorecard=_env_int("WALLET_B_MIN_SCORECARD", 50),
        risk_per_trade=_env_float("WALLET_B_RISK_PER_TRADE", 0.008),
        max_open_positions=_env_int("WALLET_B_MAX_POSITIONS", 6),
        equity_pct=_env_float("WALLET_B_EQUITY_PCT", 0.5),
        cb_daily_loss_pct=_env_float("WALLET_B_CB_DAILY_LOSS", 0.06),
        cb_max_consecutive_losses=_env_int("WALLET_B_CB_MAX_CONSEC", 5),
        cb_max_drawdown_pct=_env_float("WALLET_B_CB_MAX_DD", 0.20),
        telegram_chat_id=os.getenv("WALLET_B_TELEGRAM_CHAT_ID"),
    )
