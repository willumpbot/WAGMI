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


# Focused symbol set — backtested assets only
# Fewer symbols = faster rescan loop = better scalp coverage
DEFAULT_SYMBOLS = {
    "BTC": SymbolConfig("BTC", "BTC-USD", "bitcoin", "low"),
    "SOL": SymbolConfig("SOL", "SOL-USD", "solana", "medium"),
    "HYPE": SymbolConfig("HYPE", "HYPE-USD", "hyperliquid", "high"),
}

# Risk multipliers for zone computation (from user's original bots)
# BTC "low" widened from (1.0, 1.8) → (1.3, 2.2): original tight zones designed
# for spot trading caused 1-2% intraday futures swings to hit stops consistently.
# BTC had 38% WR and -$2,120 loss on 10d backtest with the tight multipliers.
RISK_MULTIPLIERS: Dict[str, Tuple[float, float]] = {
    "low": (1.3, 2.2),
    "medium": (1.5, 2.5),
    "high": (2.0, 3.5),
}


@dataclass
class TradingConfig:
    """Master trading configuration."""

    # General
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "paper"))
    scan_interval_s: int = field(default_factory=lambda: _env_int("SCAN_INTERVAL_S", 60))  # 60s: reduces signal churn (was 30s)
    verbose: bool = field(default_factory=lambda: _env_bool("VERBOSE", True))

    # Equity & risk
    starting_equity: float = field(default_factory=lambda: _env_float("STARTING_EQUITY", 10000.0))
    risk_per_trade: float = field(default_factory=lambda: _env_float("RISK_PER_TRADE", 0.005))
    # Was 0.02: quant approach = many small bets. 0.5% risk means a single loss
    # costs $250 on $50k, not $1,000. Law of large numbers over 40+ trades.
    vol_target_pct: float = field(default_factory=lambda: _env_float("VOL_TARGET_PCT", 0.005))
    # Vol-targeting: replaces 11-multiplier compound sizing system (single parameter).
    # Position risk scales inversely with ATR vs 1.5% baseline ATR.
    # At baseline vol (1.5% ATR): risk = vol_target_pct.
    # High vol (3% ATR): risk → 0.25×. Low vol (0.75% ATR): risk → 2× (capped).
    # Rule: need 30 trades/param for statistical validity. 4 core params = 120 trades needed.
    max_open_positions: int = field(default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 8))
    # Was 3: with 0.5% risk/trade, 8 positions = 4% total risk (same as old 2 @ 2%)
    taker_fee_bps: int = field(default_factory=lambda: _env_int("TAKER_FEE_BPS", 4))  # Hyperliquid: 3.5 bps taker, rounded up for safety

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
    max_drawdown_pct: float = field(
        default_factory=lambda: _env_float("MAX_DRAWDOWN_PCT", 0.15)
    )  # 15%: 10% was too tight for crypto, caused permanent CB lockout

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
    )  # Was 3: with 4 active strategies, 3=near-unanimous. 2-agree is realistic consensus.
    # Quant approach: more trades at smaller size. EV gates handle quality filtering.
    veto_ratio: float = field(
        default_factory=lambda: _env_float("VETO_RATIO", 1.2)
    )  # Lowered from 1.5→1.2: with min_votes=3 and only 4 active strategies,
    # 1.5x veto killed too many positive-EV signals. Fee-drag + EV gates handle quality.

    # ── Strategy Enable Flags ──
    # Disable strategies with proven negative edge. Shadow ledger tracks what-if PnL.
    strategy_lead_lag_enabled: bool = field(
        default_factory=lambda: _env_bool("STRATEGY_LEAD_LAG_ENABLED", False)
    )  # 0% WR across 8 trades, -$137/trade EV, -$1,100 net
    strategy_multi_tier_quality_enabled: bool = field(
        default_factory=lambda: _env_bool("STRATEGY_MULTI_TIER_QUALITY_ENABLED", False)
    )  # PF 0.82, -$1,223 net, 10-consecutive-loss streak, common factor in every toxic combo

    # ── BTC-Specific Risk Overrides ──
    btc_atr_multiplier: float = field(
        default_factory=lambda: _env_float("BTC_ATR_MULTIPLIER", 1.75)
    )  # Widen from default 1.0-1.25: BTC capped 33/54 trades (61%), payoff ratio 0.76:1

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

    # X/Twitter (social automation — standalone, does not affect trading)
    x_api_key: str = field(default_factory=lambda: _env("X_API_KEY", ""))
    x_api_secret: str = field(default_factory=lambda: _env("X_API_SECRET", ""))
    x_access_token: str = field(default_factory=lambda: _env("X_ACCESS_TOKEN", ""))
    x_access_secret: str = field(default_factory=lambda: _env("X_ACCESS_SECRET", ""))
    x_bearer_token: str = field(default_factory=lambda: _env("X_BEARER_TOKEN", ""))

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
        default_factory=lambda: _env_int("ROTATION_MAX_PER_HOUR", 3)
    )  # Was 1: quant approach needs more frequent rotation to cherry-pick edges
    rotation_max_per_day: int = field(
        default_factory=lambda: _env_int("ROTATION_MAX_PER_DAY", 12)
    )  # Was 4: with 0.5% risk/trade, more rotations are affordable

    # ── Leverage eligibility gate ──
    min_leverage_entry_gate: float = field(
        default_factory=lambda: _env_float("MIN_LEVERAGE_ENTRY_GATE", 1.0)
    )  # Floor for leverage gate. 1.0x = allow all non-zero leverage (2-agree signals at 1.0x
    # pass through with 0.6-0.7x risk multiplier via graduated sizing). Use 1.2+ to block
    # lower-conviction trades. Graduated sizing 1.0x–1.8x, full size above 1.8x.

    # ── Profitability shield ──
    max_portfolio_leverage: float = field(
        default_factory=lambda: _env_float("MAX_PORTFOLIO_LEVERAGE", 4.0)
    )  # Was 5.0: with 8 max positions at smaller size, tighter cap prevents overleveraging
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
    # ADX below this = ranging market, strategies should not generate signals.
    # ADX 20 is the classic threshold; below 20 means no directional trend.
    adx_min_trending: float = field(
        default_factory=lambda: _env_float("ADX_MIN_TRENDING", 10.0)
    )  # Lowered from 15→10: crypto ranges with ADX 10-15 very frequently.
    # Need 30+ trades/period for statistical WF validity; ADX 15 was blocking too many.
    # Confidence floor when market is ranging (chop_score > chop_threshold * 0.8)
    # Higher than normal floor to only allow very high conviction trades in chop
    ranging_confidence_floor: float = field(
        default_factory=lambda: _env_float("RANGING_CONFIDENCE_FLOOR", 68.0)
    )  # Lowered from 80→68: chop detector was raising floor to 80-93% and blocking ALL
    # ranging signals. 68% allows clear breakouts while filtering noise.
    # Statistical target: 30+ trades/period requires passing choppy-market signals.
    max_hold_hours: int = field(
        default_factory=lambda: _env_int("MAX_HOLD_HOURS", 48)
    )
    time_stop_hours: int = field(
        default_factory=lambda: _env_int("TIME_STOP_HOURS", 8)
    )  # Close positions that haven't hit TP1 after this many hours.
    # 61.9% exit at SL after avg 15.5h drift. 8h time stop cuts slow bleeders early.
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
    sl_atr_multiplier: float = field(
        default_factory=lambda: _env_float("SL_ATR_MULTIPLIER", 2.0)
    )  # Was 1.5: at 0.69% stops, 8bps fees consume 11.6%. At 2.0x → 0.92% stops,
    # fee drag drops to 8.7%. Fewer SL hits from wicks in volatile crypto.
    ensemble_confidence_floor: float = field(
        default_factory=lambda: _env_float("ENSEMBLE_CONFIDENCE_FLOOR", 55.0)
    )  # Lowered from 60: HTF penalty now reduces confidence by 15-20pts, floor at 60 double-penalizes. EV gate handles quality.
    max_ensemble_confidence: float = field(
        default_factory=lambda: _env_float("MAX_ENSEMBLE_CONFIDENCE", 95.0)
    )  # Raised from 92: reduces clustering at cap, lets unanimous signals get proper bonus
    # Lowered from 2.0 to 1.5: fee-aware EV gate (0.15-0.20) now handles
    # profitability filtering directly. R:R 1.5 + positive EV = viable trade.
    # The old 2.0 floor was blocking valid trades that pass EV/fee-drag gates.
    min_signal_rr: float = field(
        default_factory=lambda: _env_float("MIN_SIGNAL_RR", 1.2)
    )  # Lowered from 1.5→1.2: EV gate (min_signal_ev) already handles profitability.
    # 1.5 was blocking valid risk/reward setups. Fee-drag filter handles quality.
    min_stop_width_pct: float = field(
        default_factory=lambda: _env_float("MIN_STOP_WIDTH_PCT", 0.003)
    )  # Raised from 0.2% to 0.3%: at 0.2%, fees consume 40% of stop distance
    # Minimum expected value per dollar risked. EV = (win_prob × R:R) - (1-win_prob).
    # Filters trades where the probability × payoff doesn't justify the risk.
    # Raised from 0.10 to 0.15: at 45% WR, trades need 15%+ edge per $1
    # risked to survive fees (4bps each way = ~8bps round-trip).
    min_signal_ev: float = field(
        default_factory=lambda: _env_float("MIN_SIGNAL_EV", 0.08)
    )  # Lowered from 0.15→0.08: EV gate was #1 signal killer (blocked 39.7% at 0.15).
    # Fee-drag filter + R:R gate are the primary quality controls.
    # At 45% WR + 1.2 RR: EV = 0.45×1.2 - 0.55 = -0.01 (needs RR > 1.22 to break even).
    # 0.08 EV floor: allows 47% WR × 1.4 RR trades (EV=0.088) that fee-drag passes.
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
        default_factory=lambda: _env_float("TP_SL_RR1", 2.0)
    )
    tp_sl_rr2: float = field(
        default_factory=lambda: _env_float("TP_SL_RR2", 4.0)
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
        default_factory=lambda: _env_int("LOSS_COOLDOWN_S", 60)
    )  # Was 300 (5min): quant approach = quick re-entry. Small size makes revenge trading less risky.
    win_cooldown_s: int = field(
        default_factory=lambda: _env_int("WIN_COOLDOWN_S", 60)
    )  # Was 180 (3min): faster re-entry to capitalize on momentum after wins.
    signal_dedup_window_s: int = field(
        default_factory=lambda: _env_int("SIGNAL_DEDUP_WINDOW_S", 120)
    )  # Was 600 (10min): 2min dedup allows faster signal capture across strategies.

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

    # ── AutoOptimizer ──
    auto_optimizer_enabled: bool = field(
        default_factory=lambda: _env_bool("AUTO_OPTIMIZER_ENABLED", True)
    )
    auto_opt_min_interval_h: float = field(
        default_factory=lambda: _env_float("AUTO_OPT_MIN_INTERVAL_H", 12.0)
    )
    auto_opt_trades_per_review: int = field(
        default_factory=lambda: _env_int("AUTO_OPT_TRADES_PER_REVIEW", 15)
    )
    auto_opt_llm_review: bool = field(
        default_factory=lambda: _env_bool("AUTO_OPT_LLM_REVIEW", True)
    )
    auto_opt_degradation_threshold: float = field(
        default_factory=lambda: _env_float("AUTO_OPT_DEGRADATION_THRESHOLD", 15.0)
    )
    auto_opt_consec_loss_alert: int = field(
        default_factory=lambda: _env_int("AUTO_OPT_CONSEC_LOSS_ALERT", 4)
    )

    # ── Squeeze Detection ──
    squeeze_atr_ratio: float = field(
        default_factory=lambda: _env_float("SQUEEZE_ATR_RATIO", 0.65)
    )  # ATR compression threshold: current ATR < this * 20-bar avg ATR = squeeze

    # ── Soft Filters (Filter-to-Annotation Architecture) ──
    # When enabled, non-safety filters become annotations instead of hard rejects.
    # LLM agents see ALL signals with filter assessments and decide what to trade.
    enable_soft_filters: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SOFT_FILTERS", False)
    )  # Master switch — default OFF for safety. Enable after backtest validation.
    soft_filter_log_only: bool = field(
        default_factory=lambda: _env_bool("SOFT_FILTER_LOG_ONLY", True)
    )  # Log annotations but still hard-reject (Phase 1 validation mode)
    soft_filter_near_miss: bool = field(
        default_factory=lambda: _env_bool("SOFT_FILTER_NEAR_MISS", True)
    )  # Include near-miss signals (soft-rejected) in LLM context
    soft_filter_learning: bool = field(
        default_factory=lambda: _env_bool("SOFT_FILTER_LEARNING", True)
    )  # Enable filter accuracy feedback loop

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
    # Volatility profile: "low" (BTC-like), "medium" (SOL-like), "high" (HYPE/meme)
    # Affects chop detection sensitivity and ensemble confidence floor
    volatility_profile: str = "medium"


# Default per-symbol overrides
# Leverage caps align with Hyperliquid exchange maximums in symbol_precision.json
# risk_per_trade overrides let memecoins risk slightly less than large caps
# volatility_profile tunes chop detection + strategy sensitivity per asset
DEFAULT_SYMBOL_OVERRIDES: Dict[str, SymbolOverrides] = {
    # BTC: reduced leverage (was 25x), halved risk_per_trade — BTC lost -$2,120 on
    # 10d backtest (38% WR). Lower volatility = ATR stops proportionally tighter,
    # needs less risk per trade to compensate.
    "BTC": SymbolOverrides(max_leverage=10.0, risk_per_trade=_env_float("BTC_RISK_OVERRIDE", 0.004), volatility_profile="low"),
    # BTC risk slightly below global 0.5% since BTC ATR stops are proportionally tighter
    "SOL": SymbolOverrides(max_leverage=20.0, volatility_profile="medium"),
    "HYPE": SymbolOverrides(max_leverage=20.0, volatility_profile="high"),
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
    "risk_per_trade": 0.005,    # 0.5% risk per trade: quant approach, many small bets
    "max_open_positions": 8,    # 8 concurrent positions at 0.5% risk = 4% max exposure
    "max_portfolio_leverage": 4.0,  # Tighter cap with more positions
    "enable_smart_orders": False,
}

# Regime-conditional SL/TP multipliers (applied on top of base sl_atr_multiplier)
# Trending: wider SL (let trends breathe), wider TP (let momentum carry)
# Consolidation: tighter SL (mean-revert or stop), tighter TP (take profits before snap-back)
# High vol: widest SL (avoid wick stops), tightest TP (grab what you can)
REGIME_SL_TP_SCALARS = {
    "trending_bull":    {"sl_mult": 1.2, "tp1_mult": 1.3, "tp2_mult": 1.5},   # was tp1=0.9/tp2=0.85: inverted R:R killed trending trades
    "trending_bear":    {"sl_mult": 1.1, "tp1_mult": 1.2, "tp2_mult": 1.4},   # was tp1=0.8/tp2=0.8: same issue
    "trend":            {"sl_mult": 1.15, "tp1_mult": 1.25, "tp2_mult": 1.4},  # was tp1=0.85/tp2=0.85
    "consolidation":    {"sl_mult": 0.85, "tp1_mult": 0.9, "tp2_mult": 0.85},  # was tp1=1.2/tp2=1.3: mean-reversion should take profits fast
    "range":            {"sl_mult": 0.9, "tp1_mult": 0.95, "tp2_mult": 0.9},   # was tp1=1.1/tp2=1.2: same as consolidation
    "high_volatility":  {"sl_mult": 1.4, "tp1_mult": 1.2, "tp2_mult": 2.0},  # was tp1=0.7/tp2=0.7: same inverted R:R bug — risk 2.8 ATR to make 1.4 ATR
    "panic":            {"sl_mult": 1.5, "tp1_mult": 0.6, "tp2_mult": 0.6},  # panic: still grab what you can
    "low_liquidity":    {"sl_mult": 1.3, "tp1_mult": 0.8, "tp2_mult": 0.8},
}


# Regime-aware risk sizing: bet bigger where edge is proven, smaller where it isn't.
# 30-day backtest: consolidation 78% WR (+$3.2k), trending_bull 40% WR (-$4k).
REGIME_RISK_MULTIPLIERS = {
    "trending_bull":    0.12,   # 16.7% WR in 90d. Keep minimal exposure for learning, near-skip.
    "trending_bear":    0.15,   # Worst regime. Minimal exposure, not zero — allows learning.
    "trend":            0.7,    # generic trend, moderate caution
    "consolidation":    1.0,    # best regime: 47% WR, +$4k PnL — full size
    "range":            0.6,    # 50% WR but losses > wins. Moderate reduction.
    "high_volatility":  0.3,    # 0% WR in recent data. Near-skip.
    "panic":            0.2,    # extreme conditions — minimal exposure
    "low_liquidity":    0.3,    # 0% WR in live trades — near-skip
    "news_dislocation": 0.3,
    "unknown":          0.3,    # no edge data — be cautious
}


# Symbol-specific risk scaling: size based on validated edge per symbol.
# BTC: PF=12.64, 75% WR over 150d — full conviction
# SOL: PF=0.67, 33% WR over 90d — marginal, reduce
# HYPE: PF=0.0, 0% WR over 90d — minimal until more data
SYMBOL_RISK_MULTIPLIERS = {
    "BTC":  1.0,   # proven edge — full size
    "SOL":  0.5,   # marginal edge — half size
    "HYPE": 0.25,  # Negative EV (-$6/trade) at 33% WR. Minimal exposure until edge proven.
}

def get_symbol_risk_mult(symbol: str) -> float:
    """Return position-size multiplier for the given symbol."""
    # Strip common suffixes to match base symbol
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    return SYMBOL_RISK_MULTIPLIERS.get(base, 0.6)  # default cautious for unknown symbols


def get_regime_risk_mult(regime: str) -> float:
    """Return position-size multiplier for the given regime."""
    return REGIME_RISK_MULTIPLIERS.get(regime, 0.8)


def get_regime_sl_tp(regime: str, base_sl_mult: float, base_tp1_mult: float,
                     base_tp2_mult: float) -> tuple:
    """Apply regime-conditional scaling to SL/TP multipliers.

    Returns (adjusted_sl_mult, adjusted_tp1_mult, adjusted_tp2_mult).
    """
    scalars = REGIME_SL_TP_SCALARS.get(regime)
    if scalars is None:
        return (base_sl_mult, base_tp1_mult, base_tp2_mult)
    return (
        base_sl_mult * scalars["sl_mult"],
        base_tp1_mult * scalars["tp1_mult"],
        base_tp2_mult * scalars["tp2_mult"],
    )


LIVE_PROFILE_OVERRIDES = {
    "max_leverage": 25.0,       # Full leverage in live
    "risk_per_trade": 0.005,    # 0.5% risk per trade: quant approach, many small bets
    "max_open_positions": 8,    # 8 concurrent positions at 0.5% risk = 4% max exposure
    "max_portfolio_leverage": 4.0,  # Tighter cap with more positions
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
