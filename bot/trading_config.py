"""
Centralized configuration for the multi-strategy trading system.
All settings come from environment variables with sensible defaults.

Sections:
- General, Equity & Risk, Circuit Breakers
- Leverage, Trailing Stop, Ensemble
- Strategy Parameters (ATR multiples, confidence floors, MC params)
- Technical Indicator Periods
- Cooldowns & Time Intervals
- Feature Flags (Waves 1-4)
- Per-Symbol Overrides
- Paper-vs-Live Config Profiles
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


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
    risk_per_trade: float = field(default_factory=lambda: _env_float("RISK_PER_TRADE", 0.02))
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
    max_risk_multiplier: float = field(default_factory=lambda: _env_float("MAX_RISK_MULTIPLIER", 1.5))

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
        default_factory=lambda: _env_float("VETO_RATIO", 1.5)
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
    max_portfolio_leverage: float = field(
        default_factory=lambda: _env_float("MAX_PORTFOLIO_LEVERAGE", 5.0)
    )  # Aggregate notional cap: total_open_notional <= equity * this
    slippage_bps: int = field(
        default_factory=lambda: _env_int("SLIPPAGE_BPS", 3)
    )  # Estimated slippage in basis points (3 bps for HL perps, override higher for alts)
    min_profit_threshold_mult: float = field(
        default_factory=lambda: _env_float("MIN_PROFIT_THRESHOLD_MULT", 1.5)
    )  # Reject trades where TP1 target < this * total expected costs (was 3.0 — too strict)
    enable_funding_check: bool = field(
        default_factory=lambda: _env_bool("ENABLE_FUNDING_CHECK", True)
    )
    enable_correlation_check: bool = field(
        default_factory=lambda: _env_bool("ENABLE_CORRELATION_CHECK", True)
    )
    correlation_rejection_threshold: float = field(
        default_factory=lambda: _env_float("CORRELATION_REJECTION_THRESHOLD", 0.8)
    )
    enable_chop_detector: bool = field(
        default_factory=lambda: _env_bool("ENABLE_CHOP_DETECTOR", True)
    )
    chop_threshold: float = field(
        default_factory=lambda: _env_float("CHOP_THRESHOLD", 0.65)
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

    # ── Strategy Parameters (ATR multiples, confidence floors) ──
    # Previously hardcoded across strategy files. Now centralized.
    ensemble_confidence_floor: float = field(
        default_factory=lambda: _env_float("ENSEMBLE_CONFIDENCE_FLOOR", 72.0)
    )
    min_signal_rr: float = field(
        default_factory=lambda: _env_float("MIN_SIGNAL_RR", 1.5)
    )
    min_stop_width_pct: float = field(
        default_factory=lambda: _env_float("MIN_STOP_WIDTH_PCT", 0.002)
    )
    # Monte Carlo strategy
    mc_num_sims: int = field(
        default_factory=lambda: _env_int("MC_NUM_SIMS", 1000)
    )
    mc_forward_hours: int = field(
        default_factory=lambda: _env_int("MC_FORWARD_HOURS", 12)
    )
    mc_min_confidence: float = field(
        default_factory=lambda: _env_float("MC_MIN_CONFIDENCE", 60.0)
    )
    # Regime trend strategy
    regime_trend_r_mult: float = field(
        default_factory=lambda: _env_float("REGIME_TREND_R_MULT", 1.5)
    )
    regime_trend_tp1_mult: float = field(
        default_factory=lambda: _env_float("REGIME_TREND_TP1_MULT", 1.5)
    )
    regime_trend_tp2_mult: float = field(
        default_factory=lambda: _env_float("REGIME_TREND_TP2_MULT", 3.0)
    )
    regime_trend_min_confidence: float = field(
        default_factory=lambda: _env_float("REGIME_TREND_MIN_CONFIDENCE", 60.0)
    )
    # Multi-tier quality strategy
    multi_tier_k_mult: float = field(
        default_factory=lambda: _env_float("MULTI_TIER_K_MULT", 1.8)
    )
    multi_tier_tp1_ratio: float = field(
        default_factory=lambda: _env_float("MULTI_TIER_TP1_RATIO", 1.5)
    )
    multi_tier_tp2_ratio: float = field(
        default_factory=lambda: _env_float("MULTI_TIER_TP2_RATIO", 3.0)
    )
    # TP/SL engine defaults
    tp_sl_rr1: float = field(
        default_factory=lambda: _env_float("TP_SL_RR1", 1.5)
    )
    tp_sl_rr2: float = field(
        default_factory=lambda: _env_float("TP_SL_RR2", 2.5)
    )
    tp_sl_atr_mult: float = field(
        default_factory=lambda: _env_float("TP_SL_ATR_MULT", 1.5)
    )

    # ── Technical Indicator Periods ──
    atr_period: int = field(
        default_factory=lambda: _env_int("ATR_PERIOD", 14)
    )
    ema_short_period: int = field(
        default_factory=lambda: _env_int("EMA_SHORT_PERIOD", 20)
    )
    ema_medium_period: int = field(
        default_factory=lambda: _env_int("EMA_MEDIUM_PERIOD", 50)
    )
    ema_long_period: int = field(
        default_factory=lambda: _env_int("EMA_LONG_PERIOD", 200)
    )
    macd_fast: int = field(default_factory=lambda: _env_int("MACD_FAST", 12))
    macd_slow: int = field(default_factory=lambda: _env_int("MACD_SLOW", 26))
    macd_signal: int = field(default_factory=lambda: _env_int("MACD_SIGNAL", 9))
    rsi_period: int = field(default_factory=lambda: _env_int("RSI_PERIOD", 14))

    # ── Cooldowns & Time Intervals ──
    loss_cooldown_s: int = field(
        default_factory=lambda: _env_int("LOSS_COOLDOWN_S", 3600)
    )  # 1 hour after a loss (was 3 min — way too short for hourly candles)
    win_cooldown_s: int = field(
        default_factory=lambda: _env_int("WIN_COOLDOWN_S", 1800)
    )  # 30 min after a win (was 2 min)
    signal_dedup_window_s: int = field(
        default_factory=lambda: _env_int("SIGNAL_DEDUP_WINDOW_S", 3600)
    )

    # ── Timeframe Trend Weights ──
    tf_weight_5m: float = field(
        default_factory=lambda: _env_float("TF_WEIGHT_5M", 0.5)
    )
    tf_weight_1h: float = field(
        default_factory=lambda: _env_float("TF_WEIGHT_1H", 1.0)
    )
    tf_weight_6h: float = field(
        default_factory=lambda: _env_float("TF_WEIGHT_6H", 1.5)
    )
    tf_weight_daily: float = field(
        default_factory=lambda: _env_float("TF_WEIGHT_DAILY", 2.0)
    )

    # ── Leverage Risk Tier Caps ──
    leverage_cap_medium_risk: float = field(
        default_factory=lambda: _env_float("LEVERAGE_CAP_MEDIUM_RISK", 20.0)
    )
    leverage_cap_high_risk: float = field(
        default_factory=lambda: _env_float("LEVERAGE_CAP_HIGH_RISK", 12.0)
    )
    max_extreme_positions: int = field(
        default_factory=lambda: _env_int("MAX_EXTREME_POSITIONS", 2)
    )

    # ── Data Fetcher Resilience ──
    fetcher_max_retries: int = field(
        default_factory=lambda: _env_int("FETCHER_MAX_RETRIES", 3)
    )
    fetcher_circuit_breaker_threshold: int = field(
        default_factory=lambda: _env_int("FETCHER_CB_THRESHOLD", 5)
    )
    fetcher_circuit_breaker_reset_s: int = field(
        default_factory=lambda: _env_int("FETCHER_CB_RESET_S", 300)
    )

    # ── Health Monitoring ──
    health_port: int = field(
        default_factory=lambda: _env_int("HEALTH_PORT", 8081)
    )
    health_stall_timeout_s: int = field(
        default_factory=lambda: _env_int("HEALTH_STALL_TIMEOUT_S", 600)
    )

    @property
    def is_paper(self) -> bool:
        return self.environment != "production"

    @property
    def auto_trade(self) -> bool:
        return self.environment == "production"

    @property
    def timeframe_weights(self) -> Dict[str, float]:
        """Timeframe weights for trend scoring, as a dict."""
        return {
            "5m": self.tf_weight_5m,
            "1h": self.tf_weight_1h,
            "6h": self.tf_weight_6h,
            "daily": self.tf_weight_daily,
        }


# ── Per-Symbol Config Overrides ──────────────────────────────────────

@dataclass
class SymbolOverrides:
    """Per-symbol parameter overrides. Falls back to TradingConfig defaults."""
    max_leverage: Optional[float] = None
    risk_per_trade: Optional[float] = None
    confidence_floor: Optional[float] = None
    atr_mult_sl: Optional[float] = None
    atr_mult_tp1: Optional[float] = None
    atr_mult_tp2: Optional[float] = None
    enabled: bool = True


# Default per-symbol overrides
# Leverage caps align with Hyperliquid exchange maximums in symbol_precision.json
# risk_per_trade overrides let memecoins risk slightly less than large caps
DEFAULT_SYMBOL_OVERRIDES: Dict[str, SymbolOverrides] = {
    "BTC": SymbolOverrides(max_leverage=25.0),
    "SOL": SymbolOverrides(max_leverage=20.0),
    "HYPE": SymbolOverrides(max_leverage=20.0),
    "DOGE": SymbolOverrides(max_leverage=12.0),
    "FARTCOIN": SymbolOverrides(max_leverage=10.0),
}


def get_symbol_param(symbol: str, param: str, config: TradingConfig) -> float:
    """Get a parameter for a symbol, using per-symbol override if set, else global default."""
    overrides = DEFAULT_SYMBOL_OVERRIDES.get(symbol)
    if overrides:
        val = getattr(overrides, param, None)
        if val is not None:
            return val
    return getattr(config, param, 0.0)


# ── Paper vs Live Config Profiles ─────────────────────────────────────

PAPER_PROFILE_OVERRIDES = {
    "max_leverage": 25.0,       # Match live — paper should test real sizing
    "risk_per_trade": 0.02,     # 2% risk per trade (was 5% — too aggressive with leverage)
    "max_open_positions": 3,
    "max_portfolio_leverage": 5.0,  # Notional cap: equity * 5x (leveraged trades need headroom)
    "enable_smart_orders": False,
}

LIVE_PROFILE_OVERRIDES = {
    "max_leverage": 25.0,       # Full leverage in live
    "risk_per_trade": 0.02,     # 2% risk per trade (was 5% — too aggressive with leverage)
    "max_open_positions": 3,
    "max_portfolio_leverage": 5.0,  # Notional cap: equity * 5x (leveraged trades need headroom)
    "enable_smart_orders": True,
}


def apply_profile(config: TradingConfig) -> TradingConfig:
    """Apply paper/live profile overrides to a config instance.

    Profile overrides only apply if the corresponding env var is NOT set.
    Explicit env vars always take priority.
    """
    profile = PAPER_PROFILE_OVERRIDES if config.is_paper else LIVE_PROFILE_OVERRIDES
    for key, value in profile.items():
        env_key = key.upper()
        if os.getenv(env_key) is None:
            setattr(config, key, value)
    return config


# NOTE: Leverage calculation is handled exclusively by
# execution.leverage.LeverageManager.decide() — the single source of truth.
