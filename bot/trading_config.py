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
        default_factory=lambda: _env_int("MIN_VOTES_REQUIRED", 3)
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
        default_factory=lambda: _env_float("ML_ADJUSTMENT_WEIGHT", 0.20)
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

    # ── Profitability shield ──
    enable_chop_detector: bool = field(
        default_factory=lambda: _env_bool("ENABLE_CHOP_DETECTOR", True)
    )
    chop_threshold: float = field(
        default_factory=lambda: _env_float("CHOP_THRESHOLD", 0.55)
    )
    max_hold_hours: int = field(
        default_factory=lambda: _env_int("MAX_HOLD_HOURS", 48)
    )
    hold_limit_action: str = field(
        default_factory=lambda: _env("HOLD_LIMIT_ACTION", "tighten_sl")
    )  # "tighten_sl" or "force_close"

    # ── Regime & RL ──
    regime_min_confirmations: int = field(
        default_factory=lambda: _env_int("REGIME_MIN_CONFIRMATIONS", 3)
    )
    enable_rl_policy: bool = field(
        default_factory=lambda: _env_bool("ENABLE_RL_POLICY", True)
    )

    # ── Wave 1: Dormant feature activation ──
    enable_signal_flagger: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SIGNAL_FLAGGER", True)
    )
    enable_signal_override: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SIGNAL_OVERRIDE", True)
    )
    enable_self_teaching: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SELF_TEACHING", True)
    )
    enable_few_shot: bool = field(
        default_factory=lambda: _env_bool("ENABLE_FEW_SHOT", True)
    )
    llm_ensemble_enabled: bool = field(
        default_factory=lambda: _env_bool("LLM_ENSEMBLE_ENABLED", False)
    )
    llm_personas: str = field(
        default_factory=lambda: _env("LLM_PERSONAS", "")
    )  # e.g. "opus:1.0,sonnet:0.8"

    # ── Wave 2: Execution intelligence ──
    signal_decay_seconds: int = field(
        default_factory=lambda: _env_int("SIGNAL_DECAY_SECONDS", 180)
    )
    enable_regime_strategy_filter: bool = field(
        default_factory=lambda: _env_bool("ENABLE_REGIME_STRATEGY_FILTER", True)
    )
    dynamic_tp_scaling: bool = field(
        default_factory=lambda: _env_bool("DYNAMIC_TP_SCALING", True)
    )
    enable_liquidity_guard: bool = field(
        default_factory=lambda: _env_bool("ENABLE_LIQUIDITY_GUARD", True)
    )
    enable_smart_orders: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SMART_ORDERS", False)
    )

    # ── Wave 3: Portfolio-level alpha ──
    enable_portfolio_risk: bool = field(
        default_factory=lambda: _env_bool("ENABLE_PORTFOLIO_RISK", True)
    )
    max_portfolio_risk_pct: float = field(
        default_factory=lambda: _env_float("MAX_PORTFOLIO_RISK_PCT", 5.0)
    )
    enable_cascade_signals: bool = field(
        default_factory=lambda: _env_bool("ENABLE_CASCADE_SIGNALS", True)
    )

    # ── Wave 4: Self-evolving architecture ──
    enable_ab_testing: bool = field(
        default_factory=lambda: _env_bool("ENABLE_AB_TESTING", True)
    )
    enable_counterfactual: bool = field(
        default_factory=lambda: _env_bool("ENABLE_COUNTERFACTUAL", True)
    )
    enable_meta_learning: bool = field(
        default_factory=lambda: _env_bool("ENABLE_META_LEARNING", True)
    )
    enable_attribution: bool = field(
        default_factory=lambda: _env_bool("ENABLE_ATTRIBUTION", True)
    )

    # ── Web Dashboard ──
    enable_dashboard: bool = field(
        default_factory=lambda: _env_bool("ENABLE_DASHBOARD", True)
    )
    dashboard_port: int = field(
        default_factory=lambda: _env_int("DASHBOARD_PORT", 8080)
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


    # NOTE: Leverage calculation is handled exclusively by
    # execution.leverage.LeverageManager.decide() — the single source of truth.
    # A duplicate get_leverage_tier() was removed to prevent divergent thresholds.
