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
    "ETH": SymbolConfig("ETH", "ETH-USD", "ethereum", "low"),
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
    risk_per_trade: float = field(default_factory=lambda: _env_float("RISK_PER_TRADE", 0.10))
    # Half Kelly from backtest (WR=51.7%, payoff=1.5): f* = 19.5%, half = 9.75%
    # Using 10% = slightly above half Kelly. On $1k = $100 risk per trade.
    # With 2h time stops and profit locking, max 2-3 concurrent = 20-30% at risk.
    # For high-edge setups (SOL SELL 85% WR), Kelly says 35-71% — we're still conservative.
    # Scale down via env var for larger accounts.
    vol_target_pct: float = field(default_factory=lambda: _env_float("VOL_TARGET_PCT", 0.005))
    # Vol-targeting: replaces 11-multiplier compound sizing system (single parameter).
    # Position risk scales inversely with ATR vs 1.5% baseline ATR.
    # At baseline vol (1.5% ATR): risk = vol_target_pct.
    # High vol (3% ATR): risk → 0.25×. Low vol (0.75% ATR): risk → 2× (capped).
    # Rule: need 30 trades/param for statistical validity. 4 core params = 120 trades needed.
    max_open_positions: int = field(default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 8))
    # Was 3: with 0.5% risk/trade, 8 positions = 4% total risk (same as old 2 @ 2%)
    # SHIP-2026-04-19: Hyperliquid's actual Tier-0 taker is 45 bps (not 4).
    # Prior value was a 10× underestimate causing the EV gate to approve trades
    # with fake positive EV. See FEE_OPTIMIZATION_2026_04_17.md.
    taker_fee_bps: int = field(default_factory=lambda: _env_int("TAKER_FEE_BPS", 45))

    # Circuit breakers
    circuit_breaker_daily_loss_pct: float = field(
        default_factory=lambda: _env_float("CIRCUIT_BREAKER_DAILY_LOSS_PCT", 0.05)
    )
    circuit_breaker_cooldown_min: int = field(
        default_factory=lambda: _env_int("CIRCUIT_BREAKER_COOLDOWN_MIN", 60)
    )
    max_consecutive_losses: int = field(
        default_factory=lambda: _env_int("MAX_CONSECUTIVE_LOSSES", 3)
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
    max_sniper_leverage: float = field(default_factory=lambda: _env_float("MAX_SNIPER_LEVERAGE", 5.0))  # Hard cap for sniper trades
    max_risk_multiplier: float = field(default_factory=lambda: _env_float("MAX_RISK_MULTIPLIER", 2.0))

    # Trailing stop
    enable_trailing_stop: bool = field(
        default_factory=lambda: _env_bool("ENABLE_TRAILING_STOP", True)
    )
    trailing_stop_atr_mult: float = field(
        default_factory=lambda: _env_float("TRAILING_STOP_ATR_MULT", 2.0)
    )  # Widened from 1.5→2.0: tighter trailing was causing premature exits on winners

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
    strategy_vmc_cipher_enabled: bool = field(
        default_factory=lambda: _env_bool("STRATEGY_VMC_CIPHER_ENABLED", False)
    )  # 5% WR (1/20 recent), dead weight — disabled by audit 2026-04-03

    # ── Multi-Agent System (W4) ──
    # Enable/disable individual agents in the 9-agent specialist pipeline
    agent_regime_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_REGIME_ENABLED", True)
    )  # Regime classification (Haiku)
    agent_trade_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_TRADE_ENABLED", True)
    )  # Trade decision + thesis (Sonnet)
    agent_risk_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_RISK_ENABLED", True)
    )  # Position sizing + risk (Haiku)
    agent_critic_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_CRITIC_ENABLED", True)
    )  # Stress-testing + veto (Sonnet)
    agent_learning_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_LEARNING_ENABLED", True)
    )  # Lesson extraction (Haiku)
    agent_exit_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_EXIT_ENABLED", True)
    )  # Position exit reassessment (Haiku)
    agent_scout_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_SCOUT_ENABLED", False)
    )  # Idle-time preparation (Haiku)
    agent_overseer_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_OVERSEER_ENABLED", False)
    )  # Cross-agent monitoring (Haiku)
    agent_quant_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_QUANT_ENABLED", False)
    )  # Quant analysis (Haiku)

    # New specialist agents for learning loop (W4-ABC)
    agent_opportunist_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_OPPORTUNIST_ENABLED", False)
    )  # Pattern discovery + auto-register (Opportunist)
    agent_adversary_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_ADVERSARY_ENABLED", False)
    )  # Stress-testing proposals (Adversary)
    agent_swarm_enabled: bool = field(
        default_factory=lambda: _env_bool("AGENT_SWARM_ENABLED", False)
    )  # Meta-learning tuning (Swarm Optimizer)

    # Agent cost thresholds (min confidence required for agent to run)
    agent_regime_min_confidence: float = field(
        default_factory=lambda: _env_float("AGENT_REGIME_MIN_CONFIDENCE", 0.0)
    )  # Run regime agent always
    agent_trade_min_confidence: float = field(
        default_factory=lambda: _env_float("AGENT_TRADE_MIN_CONFIDENCE", 0.0)
    )  # Run trade agent always
    agent_risk_min_confidence: float = field(
        default_factory=lambda: _env_float("AGENT_RISK_MIN_CONFIDENCE", 0.0)
    )  # Run risk agent always
    agent_critic_min_confidence: float = field(
        default_factory=lambda: _env_float("AGENT_CRITIC_MIN_CONFIDENCE", 50.0)
    )  # Run critic agent for trades with >=50% confidence
    agent_exit_min_confidence: float = field(
        default_factory=lambda: _env_float("AGENT_EXIT_MIN_CONFIDENCE", 0.0)
    )  # Run exit agent always (on open positions)

    # Per-agent model overrides (use specific model instead of tier routing)
    agent_regime_model: str = field(
        default_factory=lambda: _env("AGENT_REGIME_MODEL", "")
    )  # e.g., "haiku" or "sonnet"
    agent_trade_model: str = field(
        default_factory=lambda: _env("AGENT_TRADE_MODEL", "")
    )
    agent_risk_model: str = field(
        default_factory=lambda: _env("AGENT_RISK_MODEL", "")
    )
    agent_critic_model: str = field(
        default_factory=lambda: _env("AGENT_CRITIC_MODEL", "")
    )
    agent_exit_model: str = field(
        default_factory=lambda: _env("AGENT_EXIT_MODEL", "")
    )

    # BTC-Specific Risk Overrides ──
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
        default_factory=lambda: _env_int("TIME_STOP_HOURS", 2)
    )  # Scalp approach: if TP1 not hit in 2h, close and re-enter.
    # Best trade was 36min. Losers sat for 6-10h bleeding.
    # Data: hold >2h = diminishing WR. Take profit or cut and re-enter.
    # Was 8h. Data: 12h time stop is optimal (+4.5R net). Gives winners more room
    # to develop while still cutting slow bleeders before they drift to SL.
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
    # Regime-aware strategy weighting: multiplicatively adjust strategy weights
    # based on the current market regime (e.g., boost bollinger_squeeze in high_vol).
    # Auto-tunes from observed per-regime-per-strategy performance over time.
    regime_strategy_weighting_enabled: bool = field(
        default_factory=lambda: _env_bool("REGIME_STRATEGY_WEIGHTING_ENABLED", True)
    )
    dynamic_tp_scaling: bool = field(
        default_factory=lambda: _env_bool("DYNAMIC_TP_SCALING", True)
    )
    # MFE-based dynamic TP/SL optimization (per-symbol data-driven levels)
    dynamic_tp_enabled: bool = field(
        default_factory=lambda: _env_bool("DYNAMIC_TP_ENABLED", True)
    )
    dynamic_tp_blend_weight: float = field(
        default_factory=lambda: _env_float("DYNAMIC_TP_BLEND_WEIGHT", 0.6)
    )  # 0.0=profile only, 1.0=MFE only. 0.6 = lean toward MFE data.
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

    # ── Cross-Asset Lead-Lag Intelligence ──
    # BTC leads SOL by ~1h (corr 0.87), ETH by ~30min (corr 0.91).
    # When BTC makes a decisive move, followers lag — boost aligned signals.
    enable_lead_lag_boost: bool = field(
        default_factory=lambda: _env_bool("ENABLE_LEAD_LAG_BOOST", True)
    )
    # BTC move threshold (%) over 15min window to trigger a lead signal
    lead_lag_btc_move_threshold: float = field(
        default_factory=lambda: _env_float("LEAD_LAG_BTC_MOVE_THRESHOLD", 0.3)
    )
    # Maximum confidence boost from lead-lag alignment (added to signal confidence)
    lead_lag_max_boost: float = field(
        default_factory=lambda: _env_float("LEAD_LAG_MAX_BOOST", 12.0)
    )
    # Minimum real-time correlation to apply boost (decays if correlation weakens)
    lead_lag_min_correlation: float = field(
        default_factory=lambda: _env_float("LEAD_LAG_MIN_CORRELATION", 0.60)
    )
    # Correlation decay factor per evaluation (exponential decay toward 0.5)
    lead_lag_correlation_decay: float = field(
        default_factory=lambda: _env_float("LEAD_LAG_CORRELATION_DECAY", 0.98)
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

    # ── Time-of-Day Sizing Filter ──
    # Data-driven hour/day multipliers from 500-candle quant analysis.
    # Adjusts position sizing (not gating) based on statistical edges.
    enable_time_sizing: bool = field(
        default_factory=lambda: _env_bool("ENABLE_TIME_SIZING", True)
    )
    # Apply boosts during PRIME hours (not just reductions during DEAD hours)
    time_sizing_allow_boost: bool = field(
        default_factory=lambda: _env_bool("TIME_SIZING_ALLOW_BOOST", True)
    )
    # Max boost cap — prevents runaway sizing from stacked multipliers
    time_sizing_max_boost: float = field(
        default_factory=lambda: _env_float("TIME_SIZING_MAX_BOOST", 1.4)
    )
    # Directional bias boost: extra sizing when trade direction matches
    # proven hour-of-day directional edge (e.g., long at 18:00 UTC)
    time_sizing_directional_boost: float = field(
        default_factory=lambda: _env_float("TIME_SIZING_DIRECTIONAL_BOOST", 1.15)
    )
    # Directional penalty: reduce sizing when trading against proven bias
    time_sizing_directional_penalty: float = field(
        default_factory=lambda: _env_float("TIME_SIZING_DIRECTIONAL_PENALTY", 0.85)
    )

    # ── Dual Wallet System ──
    dual_wallet_enabled: bool = field(
        default_factory=lambda: _env_bool("DUAL_WALLET_ENABLED", False)
    )
    wallet_a_equity_pct: float = field(
        default_factory=lambda: _env_float("WALLET_A_EQUITY_PCT", 0.5)
    )
    wallet_b_equity_pct: float = field(
        default_factory=lambda: _env_float("WALLET_B_EQUITY_PCT", 0.5)
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
        default_factory=lambda: _env_float("MIN_STOP_WIDTH_PCT", 0.004)
    )  # 0.4% minimum — allows scalp-style tight stops at high leverage.
    # At 10x with 0.5% SL: $25 risk, 5% DD on margin, exits in 5-15min.
    # The 1.0% floor was blocking all high-leverage scalps.
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

    # Minimum win probability (post-deflation). Blocks trades where the ensemble's
    # own probability estimate says the trade is below coin-flip after regime deflation.
    # Data: trades at 42%/40% WP all lost. 48% gives a small buffer above break-even.
    min_signal_win_prob: float = field(
        default_factory=lambda: _env_float("MIN_SIGNAL_WIN_PROB", 0.48)
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
        default_factory=lambda: _env_float("TP_SL_RR1", 2.0)
    )
    tp_sl_rr2: float = field(
        default_factory=lambda: _env_float("TP_SL_RR2", 4.0)
    )
    tp_sl_atr_mult: float = field(
        default_factory=lambda: _env_float("TP_SL_ATR_MULT", 1.5)
    )
    # Minimum R:R floor enforced after all ensemble SL/TP adjustments.
    # If TP1 is too close (R:R < this), TP1 is widened to meet the floor.
    # Prevents per-symbol overrides from destroying signal geometry.
    min_rr_tp1: float = field(
        default_factory=lambda: _env_float("MIN_RR_TP1", 1.5)
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
    )  # 60s: aggressive re-entry for data collection. SL + notional cap protect us.
    win_cooldown_s: int = field(
        default_factory=lambda: _env_int("WIN_COOLDOWN_S", 60)
    )  # 60s: fast re-entry to capitalize on momentum.
    signal_dedup_window_s: int = field(
        default_factory=lambda: _env_int("SIGNAL_DEDUP_WINDOW_S", 120)
    )  # 10min: 2min dedup was letting duplicate signals through (3 HYPE entries in 16min at same price).

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

    # ── LLM-First Architecture ──
    # When enabled, signals pass through SafetyFilterChain (5 gates) then go
    # directly to the LLM multi-agent pipeline. The LLM handles ALL quality
    # and sizing decisions, replacing 47 mechanical gates.
    # Requires: LLM_MODE >= 3 (SIZING) and LLM_MULTI_AGENT=true.
    # When disabled or LLM unavailable: falls back to legacy RiskFilterChain.
    llm_first_mode: bool = field(
        default_factory=lambda: _env_bool("LLM_FIRST_MODE", False)
    )
    # Dual-track mode: run BOTH paths and log divergence for validation.
    # Does not change trade execution — uses legacy path but logs what
    # LLM-first would have done differently.
    llm_first_dual_track: bool = field(
        default_factory=lambda: _env_bool("LLM_FIRST_DUAL_TRACK", False)
    )

    # ── Quant Rules (proven statistical edges hardcoded into pipeline) ──
    # Each rule is individually toggleable. Applied BEFORE the risk multiplier chain
    # as confidence boosts, so they compound with existing sizing logic.

    # Rule 1: Morning Edge — 06-12 UTC has 75% WR vs 33-45% in evening
    quant_morning_edge_enabled: bool = field(
        default_factory=lambda: _env_bool("QUANT_MORNING_EDGE_ENABLED", True)
    )
    quant_morning_edge_boost: float = field(
        default_factory=lambda: _env_float("QUANT_MORNING_EDGE_BOOST", 1.2)
    )  # 1.2x confidence boost for signals in 06-12 UTC window

    # Rule 2: BTC SHORT Edge — 67% WR live, historically strongest setup
    quant_btc_short_edge_enabled: bool = field(
        default_factory=lambda: _env_bool("QUANT_BTC_SHORT_EDGE_ENABLED", True)
    )
    quant_btc_short_edge_boost: float = field(
        default_factory=lambda: _env_float("QUANT_BTC_SHORT_EDGE_BOOST", 1.15)
    )  # 1.15x confidence boost for BTC SELL signals

    # Rule 3: HYPE BUY in High Vol — strongest edge at P50-P75 ATR percentile
    quant_hype_highvol_enabled: bool = field(
        default_factory=lambda: _env_bool("QUANT_HYPE_HIGHVOL_ENABLED", True)
    )
    quant_hype_highvol_boost: float = field(
        default_factory=lambda: _env_float("QUANT_HYPE_HIGHVOL_BOOST", 1.2)
    )  # 1.2x confidence boost for HYPE BUY in high_volatility regime

    # Rule 4: Conviction Multiplier — size up on high-confidence multi-agree
    quant_conviction_mult_enabled: bool = field(
        default_factory=lambda: _env_bool("QUANT_CONVICTION_MULT_ENABLED", True)
    )
    quant_conviction_risk_mult: float = field(
        default_factory=lambda: _env_float("QUANT_CONVICTION_RISK_MULT", 1.3)
    )  # 1.3x risk multiplier when confidence > 80% AND 2+ strategies agree
    quant_conviction_min_confidence: float = field(
        default_factory=lambda: _env_float("QUANT_CONVICTION_MIN_CONFIDENCE", 80.0)
    )
    quant_conviction_min_agree: int = field(
        default_factory=lambda: _env_int("QUANT_CONVICTION_MIN_AGREE", 2)
    )

    # ── Confidence Calibration ──
    # Corrects raw ensemble confidence using historical win-rate data.
    # 90-100% raw confidence often loses; 70-79% is the sweet spot.
    # Calibration deflates overconfident bands and inflates underconfident ones.
    confidence_calibration_enabled: bool = field(
        default_factory=lambda: _env_bool("CONFIDENCE_CALIBRATION_ENABLED", True)
    )
    calibration_window: int = field(
        default_factory=lambda: _env_int("CALIBRATION_WINDOW", 50)
    )  # Number of recent trades (EWMA-weighted) used to build calibration curve

    # ── Adaptive Sizing (Anti-Martingale) ──
    # Size up when hot (winning streak), size down when cold (losing streak).
    # Data insight: larger positions show 64-73% WR vs 42-45% for smaller ones.
    adaptive_sizing_enabled: bool = field(
        default_factory=lambda: _env_bool("ADAPTIVE_SIZING_ENABLED", True)
    )
    adaptive_sizing_window: int = field(
        default_factory=lambda: _env_int("ADAPTIVE_SIZING_WINDOW", 20)
    )  # Rolling window of recent trades for heat calculation
    adaptive_sizing_max_boost: float = field(
        default_factory=lambda: _env_float("ADAPTIVE_SIZING_MAX_BOOST", 1.5)
    )  # Max sizing multiplier when on a hot streak
    adaptive_sizing_min_floor: float = field(
        default_factory=lambda: _env_float("ADAPTIVE_SIZING_MIN_FLOOR", 0.5)
    )  # Min sizing multiplier when on a cold streak

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
    # MFE-optimal TP1/SL as percentage of entry price (from MFE/MAE analysis)
    mfe_tp1_pct: Optional[float] = None  # e.g. 0.38 means 0.38%
    mfe_sl_pct: Optional[float] = None   # e.g. 0.72 means 0.72%


# Default per-symbol overrides
# Leverage caps align with Hyperliquid exchange maximums in symbol_precision.json
# risk_per_trade overrides let memecoins risk slightly less than large caps
# volatility_profile tunes chop detection + strategy sensitivity per asset
DEFAULT_SYMBOL_OVERRIDES: Dict[str, SymbolOverrides] = {
    # BTC: Best live edge (SHORT 100% WR). No special overrides — let Kelly size it
    # like everything else. Global risk_per_trade=10%, global max_leverage=25x.
    # The leverage manager + stop width will produce the right leverage naturally.
    "BTC": SymbolOverrides(volatility_profile="low",
                           mfe_tp1_pct=0.38, mfe_sl_pct=0.72),
    "ETH": SymbolOverrides(max_leverage=20.0, volatility_profile="low",
                           mfe_tp1_pct=0.44, mfe_sl_pct=0.90),
    "SOL": SymbolOverrides(max_leverage=20.0, volatility_profile="medium",
                           mfe_tp1_pct=0.51, mfe_sl_pct=0.96),
    "HYPE": SymbolOverrides(
        max_leverage=20.0,
        volatility_profile="high",
        atr_mult_sl=2.0,   # Wide stops: HYPE has 2x BTC vol. 2.2x blocked all trades (R:R too low). 2.0x = compromise.
                            # Need to survive the first 6h of mean-reversion volatility.
        atr_mult_tp1=3.0,  # TP1 must be >= 1.5x SL width for R:R >= 1.5. Was 1.0 which gave R:R=0.75,
                            # causing ensemble to reject 498 valid HYPE signals/day as negative EV.
        mfe_tp1_pct=0.78, mfe_sl_pct=1.34,
    ),
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
    "risk_per_trade": 0.10,     # 10% risk per trade: half Kelly (backtest f*=19.5%)
    "max_open_positions": 8,    # 8 concurrent positions at 1.5% risk = 12% max exposure
    "max_portfolio_leverage": 4.0,  # Tighter cap with more positions
    "enable_smart_orders": False,
}

# Regime-conditional SL/TP multipliers (applied on top of base sl_atr_multiplier)
# Trending: wider SL (let trends breathe), wider TP (let momentum carry)
# Consolidation: tighter SL (mean-revert or stop), tighter TP (take profits before snap-back)
# High vol: widest SL (avoid wick stops), tightest TP (grab what you can)
REGIME_SL_TP_SCALARS = {
    "trending_bull":    {"sl_mult": 1.2, "tp1_mult": 1.3, "tp2_mult": 1.5},
    "trending_bear":    {"sl_mult": 1.1, "tp1_mult": 1.2, "tp2_mult": 1.4},
    "trend":            {"sl_mult": 1.15, "tp1_mult": 1.25, "tp2_mult": 1.4},
    "trending":         {"sl_mult": 1.2, "tp1_mult": 1.3, "tp2_mult": 1.5},   # 52% WR, +$118 — wider SL like trending_bull
    "consolidation":    {"sl_mult": 0.85, "tp1_mult": 0.9, "tp2_mult": 0.85},
    # range/ranging: 94% SL hit rate, 25% WR → widen SL to clear noise, TP fast
    "range":            {"sl_mult": 1.4, "tp1_mult": 0.8, "tp2_mult": 0.85},  # was sl=0.9: 94% SL hits, need wider stop
    "ranging":          {"sl_mult": 1.4, "tp1_mult": 0.8, "tp2_mult": 0.85},  # same — data: 25% WR n=16
    "high_volatility":  {"sl_mult": 1.4, "tp1_mult": 1.2, "tp2_mult": 2.0},
    "panic":            {"sl_mult": 1.5, "tp1_mult": 0.6, "tp2_mult": 0.6},
    # illiquid: 82% SL hit rate, 28% WR, avg SL=1.43% vs ATR=0.84% → SL/ATR=1.70x. Need 2.5x.
    "low_liquidity":    {"sl_mult": 1.5, "tp1_mult": 0.75, "tp2_mult": 0.75},  # was sl=1.3: 82% SL hits
    "illiquid":         {"sl_mult": 1.5, "tp1_mult": 0.75, "tp2_mult": 0.75},  # same — data: 28% WR n=57
    # "unknown" intentionally omitted — pass through base values unchanged
}


# Regime-aware risk sizing: bet bigger where edge is proven, smaller where it isn't.
# 30-day backtest: consolidation 78% WR (+$3.2k), trending_bull 40% WR (-$4k).
# Updated 2026-04-12 from 105 live trades. Comments show ACTUAL live performance.
REGIME_RISK_MULTIPLIERS = {
    "trending_bear":    1.0,    # THE GOLDEN REGIME: +$406, 75% WR, PF=18.4 — FULL SIZE
    "trending_bull":    1.0,    # +$45, 67% WR, PF=4546 — FULL SIZE
    # Updated 2026-04-23 from 164 live trades in trade_dna:
    "trending":         1.0,    # 52% WR n=52 +$118 — profitable regime, full size
    "high_volatility":  0.85,   # small sample but promising
    "illiquid":         0.50,   # 28% WR n=57 -$83 — down from 0.70: live data proves losing regime
    "trend":            0.50,   # TRAP: -$200, 18% WR, PF=0.15 — weak ADX, treat like range
    "range":            0.45,   # 25% WR n=16 -$46 — consistent loser
    "ranging":          0.45,   # same as range — 25% WR n=16
    "consolidation":    0.30,   # DISASTER: -$169, 0% WR, PF=0 — minimum size
    "panic":            0.50,   # No live data — cautious
    "low_liquidity":    0.40,   # Canonical name for illiquid — minimal
    "news_dislocation": 0.50,   # Unpredictable — cautious
    "unknown":          0.45,   # 36% WR n=39 -$61 — losing regime, reduced from 0.50
}


# Symbol-specific risk scaling from 105 live trades (2026-04-12).
# ETH: PF=3.98, 50% WR, +$39 — best per-trade avg ($2.77)
# BTC: PF=1.41, 38% WR, +$31 — clean when leverage controlled
# SOL: PF=1.05, 37% WR, +$25 — high variance, W15 was +$137
# HYPE: PF=0.50, 24% WR, -$36 — WORST SYMBOL, losing consistently
SYMBOL_RISK_MULTIPLIERS = {
    "ETH":  1.0,   # Best symbol by PnL/trade. Full size.
    "BTC":  0.90,  # Solid but needs leverage control (<=7x).
    "SOL":  0.80,  # High variance. Great in trending_bear, bad elsewhere.
    "HYPE": 0.60,  # LOSING SYMBOL: -$36, 24% WR, PF=0.5. Reduce until data improves.
}

# Symbol+side risk scaling: penalize specific directional trades with weak edge.
# 30-day backtest analysis (2026-03-30):
#   SOL LONG: 13 trades, 46% WR, -$1,209 PnL (losers hold 7-36 days before SL)
#   SOL SHORT: 13 trades, 62% WR, +$2,353 PnL
# SOL LONG winners hit TP1 instantly (0h); losers bleed for weeks. Structural issue.
# Reducing SOL LONG to 0.35x preserves the signal for data collection but limits damage.
SYMBOL_SIDE_RISK_MULTIPLIERS: Dict[tuple, float] = {
    # AGGRESSIVE DATA COLLECTION — trade everything, collect data, learn.
    # Every direction open. SL enforcement + notional cap handles risk.
    ("SOL", "BUY"):  0.70,
    ("SOL", "SELL"): 1.3,   # Big winners came from here (+$129, +$99)
    ("BTC", "BUY"):  0.70,
    ("BTC", "SELL"): 1.3,   # Best live edge (100% WR)
    ("ETH", "BUY"):  0.70,
    ("ETH", "SELL"): 0.70,
    ("HYPE", "BUY"): 0.70,
    ("HYPE", "SELL"):1.2,
}

# Per-symbol lead-lag configuration: empirical lag times and correlations.
# Used by LeadLagBoostEngine to generate confidence boosts for follower assets.
# lag_minutes: (min, max) expected lag behind BTC
# correlation: empirical correlation coefficient (0-1)
# beta: follower amplification factor (1.2 = follower moves 1.2x BTC's %)
# boost_cap: maximum confidence boost for this symbol from lead-lag
LEAD_LAG_SYMBOL_CONFIG = {
    "SOL": {
        "lag_minutes": (30, 60),       # SOL lags BTC by 30-60 min
        "correlation": 0.87,
        "beta": 1.16,
        "boost_cap": 12.0,
    },
    "ETH": {
        "lag_minutes": (15, 30),       # ETH lags BTC by 15-30 min
        "correlation": 0.91,
        "beta": 1.20,
        "boost_cap": 10.0,            # Lower cap: ETH follows faster, less edge
    },
    "HYPE": {
        "lag_minutes": (15, 45),       # HYPE less predictable
        "correlation": 0.44,
        "beta": 1.50,
        "boost_cap": 5.0,             # Low cap: weak correlation
    },
}


# Setup exit STRATEGY (not fixed TPs — those don't work on these assets).
# BTC moves 0.3%/h, SOL 0.4%/h, HYPE 0.56%/h. Fixed 1-1.5% TPs are coinflips.
# Our actual winners (BTC SHORT +$53, +$38) all used TRAILING stops.
# Strategy: TP1 at 1R to de-risk 50%, let rest trail. Time stop if flat.
SETUP_OPTIMAL_EXITS: Dict[str, Dict[str, float]] = {
    "SOL_SELL": {"tp1_r": 1.0, "tp1_close_pct": 0.5, "trail_atr": 1.0, "time_stop_h": 12, "edge": "tier1"},
    "BTC_SELL": {"tp1_r": 1.0, "tp1_close_pct": 0.5, "trail_atr": 1.0, "time_stop_h": 8, "edge": "tier1"},
    "HYPE_SELL":{"tp1_r": 1.0, "tp1_close_pct": 0.5, "trail_atr": 1.2, "time_stop_h": 12, "edge": "tier1"},
    "ETH_BUY":  {"tp1_r": 1.0, "tp1_close_pct": 0.5, "trail_atr": 1.0, "time_stop_h": 8, "edge": "tier2"},
    "HYPE_BUY": {"tp1_r": 1.0, "tp1_close_pct": 0.5, "trail_atr": 1.2, "time_stop_h": 12, "edge": "tier2"},
}


def get_setup_exit(symbol: str, side: str) -> dict:
    """Return optimal exit profile for a setup. Empty dict if not configured."""
    key = f"{symbol}_{side}"
    return SETUP_OPTIMAL_EXITS.get(key, {})


def get_lead_lag_config(symbol: str) -> dict:
    """Return lead-lag configuration for a symbol. Returns empty dict if not configured."""
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    return LEAD_LAG_SYMBOL_CONFIG.get(base, {})


def get_symbol_risk_mult(symbol: str) -> float:
    """Return position-size multiplier for the given symbol.

    If trade_dna has >= 15 trades for this symbol, blends static with live WR.
    """
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    static_mult = SYMBOL_RISK_MULTIPLIERS.get(base, 0.70)
    try:
        from llm.dynamic_thresholds import get_dynamic_thresholds
        dt = get_dynamic_thresholds()
        dt._maybe_refresh()
        sym_data = dt._symbol_data.get(base)
        if sym_data and sym_data["n"] >= 15:
            live_mult = _wr_to_risk_mult(sym_data["wr"])
            blend = min(1.0, (sym_data["n"] - 15) / 35)
            return round(static_mult * (1 - blend) + live_mult * blend, 3)
    except Exception:
        pass
    return static_mult


def get_symbol_side_risk_mult(symbol: str, side: str) -> float:
    """Return position-size multiplier for a specific symbol+side combo.

    Allows penalizing directional trades with weak historical edge
    (e.g., SOL LONG has 46% WR and negative PnL while SOL SHORT is profitable).
    Returns 1.0 (no adjustment) for combos not in SYMBOL_SIDE_RISK_MULTIPLIERS.
    """
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    # Normalize side: LONG->BUY, SHORT->SELL for consistent lookup
    normalized_side = "BUY" if side.upper() in ("BUY", "LONG") else "SELL"
    return SYMBOL_SIDE_RISK_MULTIPLIERS.get((base, normalized_side), 1.0)


def _wr_to_risk_mult(wr: float) -> float:
    """Map live win rate to a risk multiplier."""
    if wr < 0.25:
        return 0.45
    if wr < 0.35:
        return 0.55
    if wr < 0.45:
        return 0.70
    if wr < 0.55:
        return 0.90
    return 1.0


def get_regime_risk_mult(regime: str) -> float:
    """Return position-size multiplier for the given regime.

    If trade_dna has >= 15 trades for this regime, use live win rate.
    Otherwise fall back to the calibrated static table.
    """
    try:
        from llm.dynamic_thresholds import get_dynamic_thresholds
        stats = get_dynamic_thresholds().get_regime_stats(regime)
        if stats and stats["n"] >= 15:
            live_mult = _wr_to_risk_mult(stats["wr"])
            static_mult = REGIME_RISK_MULTIPLIERS.get(regime, 0.8)
            # Blend: weight live data more as n grows (full trust at n=50+)
            blend = min(1.0, (stats["n"] - 15) / 35)
            return round(static_mult * (1 - blend) + live_mult * blend, 3)
    except Exception:
        pass
    return REGIME_RISK_MULTIPLIERS.get(regime, 0.8)


def get_regime_sl_tp(regime: str, base_sl_mult: float, base_tp1_mult: float,
                     base_tp2_mult: float) -> tuple:
    """Apply regime-conditional scaling to SL/TP multipliers.

    Blends static REGIME_SL_TP_SCALARS with a live data-driven SL boost from
    DynamicThresholds. When a regime's SL hit rate in trade_dna exceeds the
    system-optimal ~72%, the SL scalar is widened proportionally so stops
    adapt to actual market noise levels rather than staying frozen at config values.

    Returns (adjusted_sl_mult, adjusted_tp1_mult, adjusted_tp2_mult).
    """
    scalars = REGIME_SL_TP_SCALARS.get(regime)
    if scalars is None:
        return (base_sl_mult, base_tp1_mult, base_tp2_mult)

    sl_scalar = scalars["sl_mult"]

    # Layer dynamic SL boost from live SL-hit-rate data
    try:
        from llm.dynamic_thresholds import get_dynamic_thresholds
        dynamic_boost = get_dynamic_thresholds().get_dynamic_sl_boost(regime, sl_scalar)
        if dynamic_boost > 0:
            sl_scalar = sl_scalar + dynamic_boost
    except Exception:
        pass  # Never block a trade on a boost computation error

    return (
        base_sl_mult * sl_scalar,
        base_tp1_mult * scalars["tp1_mult"],
        base_tp2_mult * scalars["tp2_mult"],
    )


LIVE_PROFILE_OVERRIDES = {
    "max_leverage": 25.0,       # Full leverage in live
    "risk_per_trade": 0.10,     # 10% risk per trade: half Kelly (backtest f*=19.5%)
    "max_open_positions": 8,    # 8 concurrent positions at 1.5% risk = 12% max exposure
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
