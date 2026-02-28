"""
Centralized configuration for the multi-strategy trading system.
All settings come from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


@dataclass
class SymbolConfig:
    """Configuration for a tradeable symbol."""
    name: str
    coinbase_pair: str  # e.g. "BTC-USD"
    coingecko_id: str   # e.g. "bitcoin"
    risk_tier: str      # "low", "medium", "high"


# Focused symbol set — 3 large caps + 3 high-volume small caps
# Fewer symbols = faster rescan loop = better scalp coverage
DEFAULT_SYMBOLS = {
    # Large caps (priority)
    "BTC": SymbolConfig("BTC", "BTC-USD", "bitcoin", "low"),
    "SOL": SymbolConfig("SOL", "SOL-USD", "solana", "medium"),
    "HYPE": SymbolConfig("HYPE", "HYPE-USD", "hyperliquid", "medium"),
    # Small caps (high volume memes)
    "DOGE": SymbolConfig("DOGE", "DOGE-USD", "dogecoin", "high"),
    "PEPE": SymbolConfig("PEPE", "PEPE-USD", "pepe", "high"),
    "FARTCOIN": SymbolConfig("FARTCOIN", "FARTCOIN-USD", "fartcoin", "high"),
}

# Risk multipliers for zone computation (from user's original bots)
RISK_MULTIPLIERS: Dict[str, Tuple[float, float]] = {
    "low": (1.0, 1.8),
    "medium": (1.5, 2.5),
    "high": (2.0, 3.5),
}


@dataclass
class TradingConfig:
    """Master trading configuration."""

    # General
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "paper"))
    scan_interval_s: int = field(default_factory=lambda: _env_int("SCAN_INTERVAL_S", 30))
    verbose: bool = field(default_factory=lambda: _env_bool("VERBOSE", True))

    # Equity & risk
    starting_equity: float = field(default_factory=lambda: _env_float("STARTING_EQUITY", 10000.0))
    risk_per_trade: float = field(default_factory=lambda: _env_float("RISK_PER_TRADE", 0.01))
    max_open_positions: int = field(default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 3))
    taker_fee_bps: int = field(default_factory=lambda: _env_int("TAKER_FEE_BPS", 5))

    # Circuit breakers
    circuit_breaker_daily_loss_pct: float = field(
        default_factory=lambda: _env_float("CIRCUIT_BREAKER_DAILY_LOSS_PCT", 0.05)
    )
    circuit_breaker_cooldown_min: int = field(
        default_factory=lambda: _env_int("CIRCUIT_BREAKER_COOLDOWN_MIN", 60)
    )
    max_consecutive_losses: int = field(
        default_factory=lambda: _env_int("MAX_CONSECUTIVE_LOSSES", 5)
    )
    cb_conf_override_pct: float = field(
        default_factory=lambda: _env_float("CB_CONF_OVERRIDE_PCT", 0.92)
    )

    # Leverage tiers: (min_confidence, max_confidence) -> leverage
    enable_leverage: bool = field(default_factory=lambda: _env_bool("ENABLE_LEVERAGE", True))
    max_leverage: float = field(default_factory=lambda: _env_float("MAX_LEVERAGE", 25.0))

    # Trailing stop
    enable_trailing_stop: bool = field(
        default_factory=lambda: _env_bool("ENABLE_TRAILING_STOP", True)
    )
    trailing_stop_atr_mult: float = field(
        default_factory=lambda: _env_float("TRAILING_STOP_ATR_MULT", 1.5)
    )

    # Strategy ensemble
    ensemble_mode: str = field(
        default_factory=lambda: _env("ENSEMBLE_MODE", "weighted_veto")
    )  # "voting", "weighted_veto", "weighted", "best"
    min_votes_required: int = field(
        default_factory=lambda: _env_int("MIN_VOTES_REQUIRED", 2)
    )
    veto_ratio: float = field(
        default_factory=lambda: _env_float("VETO_RATIO", 1.1)
    )

    # ML
    enable_ml: bool = field(default_factory=lambda: _env_bool("ENABLE_ML", True))
    ml_min_samples: int = field(default_factory=lambda: _env_int("ML_MIN_SAMPLES", 20))
    ml_retrain_interval: int = field(
        default_factory=lambda: _env_int("ML_RETRAIN_INTERVAL", 10)
    )
    ml_adjustment_weight: float = field(
        default_factory=lambda: _env_float("ML_ADJUSTMENT_WEIGHT", 0.4)
    )

    # Regime (for Bot 3)
    htf_hours: int = field(default_factory=lambda: _env_int("HTF_HOURS", 16))

    # Alerts
    discord_webhook: str = field(default_factory=lambda: _env("DISCORD_WEBHOOK", ""))
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID", ""))

    # Trade rotation
    enable_rotation: bool = field(
        default_factory=lambda: _env_bool("ENABLE_ROTATION", True)
    )
    rotation_min_hold_s: int = field(
        default_factory=lambda: _env_int("ROTATION_MIN_HOLD_S", 300)
    )
    rotation_global_cooldown_s: int = field(
        default_factory=lambda: _env_int("ROTATION_GLOBAL_COOLDOWN_S", 600)
    )
    rotation_max_per_hour: int = field(
        default_factory=lambda: _env_int("ROTATION_MAX_PER_HOUR", 2)
    )
    rotation_max_per_day: int = field(
        default_factory=lambda: _env_int("ROTATION_MAX_PER_DAY", 6)
    )

    # API integration
    api_base_url: str = field(default_factory=lambda: _env("BASE_URL", "http://api:8000"))
    api_key: str = field(default_factory=lambda: _env("NUNUIRL_API_KEY", _env("HEYANON_API_KEY", "")))
    strategy_id: str = field(default_factory=lambda: _env("STRATEGY_ID", "multi-strategy"))

    @property
    def is_paper(self) -> bool:
        return self.environment != "production"

    @property
    def auto_trade(self) -> bool:
        return self.environment == "production"


def get_leverage_tier(confidence: float, num_strategies_agree: int, total_strategies: int) -> float:
    """
    Determine leverage based on confidence and strategy agreement.
    Returns leverage multiplier. Minimum 2x (no spot trading).

    Tiers:
      <60%  confidence -> no trade
      60-69% -> 2x (low leverage)
      70-79% -> 2-3x
      80-89% -> 3-5x
      90-94% -> 5-10x
      95%+   -> 10-25x (RARE: requires all strategies to agree)
    """
    if confidence < 60:
        return 0.0  # no trade

    if confidence < 70:
        return 2.0  # minimum low leverage

    if confidence < 80:
        return 2.0 + (confidence - 70) / 10.0  # 2.0 to 3.0

    if confidence < 90:
        base = 3.0 + 2.0 * (confidence - 80) / 10.0  # 3.0 to 5.0
        if num_strategies_agree >= 3:
            base = min(base * 1.2, 5.0)
        return base

    if confidence < 95:
        base = 5.0 + 5.0 * (confidence - 90) / 5.0  # 5.0 to 10.0
        if num_strategies_agree < 3:
            base = min(base, 7.0)  # cap without consensus
        return base

    # 95%+ RARE extreme leverage
    if num_strategies_agree >= total_strategies and total_strategies >= 3:
        return min(10.0 + 15.0 * (confidence - 95) / 5.0, 25.0)  # 10-25x
    elif num_strategies_agree >= 3:
        return min(10.0 + 5.0 * (confidence - 95) / 5.0, 15.0)  # 10-15x
    else:
        return 10.0  # cap at 10x without full consensus
