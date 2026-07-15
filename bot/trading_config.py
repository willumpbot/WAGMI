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
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


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
    # XRP added 2026-06-25 as supply-side volume lever (one-at-a-time expansion).
    # tier="medium" maps to RISK_MULTIPLIERS (1.5, 2.5) for zone width.
    # Position-risk is bounded conservatively via DEFAULT_SYMBOL_OVERRIDES["XRP"]
    # (max_leverage=10, risk_per_trade=0.05) + SYMBOL_RISK_MULTIPLIERS["XRP"]=0.60
    # so n<10 uncalibrated trades stay small until the dynamic floor calibrates.
    "XRP": SymbolConfig("XRP", "XRP-USD", "ripple", "medium"),
    # POPCAT (owner-requested 2026-07-14) FAILED validation — 21d backtest: 37 trades, 32% WR
    # (below 39.9% break-even), -$315 net, <60%-conf bucket 9% WR/-$210. No edge currently, so
    # NOT added to the live universe (honoring the backtest-before-add rule). Wiring kept dormant
    # (fetcher map + overrides below + risk mult) for fast re-validation if POPCAT's regime shifts
    # or to enable shadow-only data tracking. To activate for live: re-add the SymbolConfig line
    # below AND confirm a passing backtest first.
    # "POPCAT": SymbolConfig("POPCAT", "POPCAT-USD", "popcat", "high"),  # dormant (see above)
    # GOAT (2026-07-14 candidate) — 0-position backtest (insufficient multi-TF history) + only marginal
    # screen edge; NOT validated, not added. Fetcher map kept dormant. Re-test if it builds more history.
    # "GOAT": SymbolConfig("GOAT", "GOAT-USD", "goatseus-maximus", "high"),
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
    # 2026-06-02 fee correction: "45 bps" was wrong by 10x. Hyperliquid Tier-0 taker
    # is 0.045% = 4.5 bps. 45 bps = 0.45% -- inflated fees 10x, turning breakeven
    # trades into logged losses. Using 5 bps as conservative round-up. (desktop e02f265)
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
    # LIVING VALUES note (2026-07-15): ledger shows range/consolidation are net
    # losers (n=107 combined, -$582) and llm/dynamic_thresholds.get_confidence_floor
    # already computes a live per-regime floor (range n=23 -> 71) that should
    # govern in strategies/ensemble.py's moderate-chop blend; this 68.0 is meant
    # to be consumed ONLY as that live path's low-n fallback argument (see
    # strategies/ensemble.py — out of scope for this file), not applied directly.
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
    # Max boost cap — prevents runaway sizing from stacked multipliers.
    # LIVING VALUES note (2026-07-15): this is a safety ceiling, kept as-is.
    # The path it governs (execution/time_sizing.py's frozen April-2026
    # _HOUR_BIAS/_SESSION_MULTIPLIERS tables) is D11 SHADOW by default
    # (TIME_SIZING_ENFORCE unset -> applied=1.0) and is ledger-inverted if ever
    # enforced: paper_trades/*.csv shows DEAD hours (would-cut 0.5x) avg
    # +$11.73/tr n=72 (best bucket) while PRIME hours (would-boost) avg
    # +$3.52/tr n=77. Fix belongs in execution/time_sizing.py (out of scope
    # for this file) — the enforce path there must be live-ledger-computed,
    # never fall back to the static tables.
    time_sizing_max_boost: float = field(
        default_factory=lambda: _env_float("TIME_SIZING_MAX_BOOST", 1.4)
    )
    # Directional bias boost: extra sizing when trade direction matches
    # proven hour-of-day directional edge (e.g., long at 18:00 UTC).
    # LIVING VALUES note (2026-07-15): the static _HOUR_BIAS table this
    # multiplies against (execution/time_sizing.py) is INVERTED vs the ledger
    # — boost-aligned slices avg -$10.12/tr (n=27) vs penalty-opposed +$0.99
    # (n=42). Harmless today only because TIME_SIZING_ENFORCE is unset (D11
    # shadow, 1.0x applied). Do not enforce until execution/time_sizing.py's
    # bias table is live-computed (n>=13 per hour-side slice) — out of scope
    # for this file.
    time_sizing_directional_boost: float = field(
        default_factory=lambda: _env_float("TIME_SIZING_DIRECTIONAL_BOOST", 1.15)
    )
    # Directional penalty: reduce sizing when trading against proven bias.
    # LIVING VALUES note (2026-07-15): same inversion as the boost above — the
    # slice this 0.85x would shrink (opposed to static bias) realizes +$7.49/tr
    # n=29 (incl. the bot's best edge, h14/15 SHORTs +$14.80/tr n=15), while the
    # slice the paired 1.15x would grow realizes -$2.98/tr n=33. Dormant via D11
    # shadow; do not re-arm without a live-computed bias table in
    # execution/time_sizing.py (out of scope for this file).
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
        default_factory=lambda: _env_float("ENSEMBLE_CONFIDENCE_FLOOR", 20.0)
    )  # LIVING VALUES fix 2026-07-15: code default corrected 55.0 -> 20.0 to match
    # the runtime floor already in force (.env ENSEMBLE_CONFIDENCE_FLOOR=20 +
    # LLM_FIRST_MODE pins ensemble floor to min(adaptive_floor, config)=20). The
    # old 55.0 was a dormant silent-gate: data/trade_ledger.csv (n=99, test rows
    # excluded) shows conf<55 n=12 WR=67% avg +$0.29/tr while conf 55-80 n=79
    # loses -$117.69 combined (avg -$0.59 to -$2.11/tr) — a 55 floor blocks the
    # non-losing low band and admits the losing band. The governing live path is
    # feedback/adaptive_confidence.py AdaptiveConfidenceFloor (WR/EV per bin,
    # bounded gradual updates); this field is only the bootstrap/env override
    # consumed by backtest/engine.py, manual/runner.py, param_optimizer.py.
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
        default_factory=lambda: _env_float("MIN_STOP_WIDTH_PCT", 0.005)
    )  # 0.5% minimum. Was 0.4%, raised 2026-06-03: live data showed 60/120 SL-hit trades
    # had stop < 0.5%; BTC noise is 0.37% so 0.4% stops were inside the noise band.
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

    # Rule 3 (HYPE BUY high-vol x1.2) DELETED 2026-07-15 (LIVING VALUES audit):
    # realized ledger paper_trades/trades_*.csv shows HYPE BUY (LONG) is n=17,
    # net -$584.10, avg -$34.36/trade, 41% WR — the WORST setup on the entire
    # ledger (vs ETH SHORT +$20.37/tr best), while this rule claimed it was the
    # "strongest edge" and boosted it 1.2x. Mirrors the Rule 2 (BTC short boost)
    # deletion precedent. Per THE_STANDARD §2b the stat may re-enter only as
    # labeled LLM context, never as a mechanical multiplier; any future
    # HYPE_BUY edge must earn its way back via live n>=13 dollar-positive
    # re-validation (see feedback.live_edge / SYMBOL_RISK_MULTIPLIERS["HYPE"]
    # below, which already penalizes HYPE to 0.40x from realized data).
    # Companion deletion of the core/signal_pipeline.py Rule 3 block and the
    # test_quant_rules.py / test_duplicate_prevention.py references is
    # tracked separately (out of scope for this file-only change).

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
    # XRP: NEW symbol (added 2026-06-25), n=0 history. Bound the uncalibrated period
    # (combo/regime gates have no data, dynamic floor falls to _DEFAULT_FLOOR=64).
    # Most-conservative position sizing available: lowest leverage cap (10x, half of
    # the 20x peers and below the 20x exchange max in symbol_precision.json) and
    # risk_per_trade=0.05 (half the global 0.10). volatility_profile="medium" matches
    # the medium risk_tier. Tightens until n>=10 trades calibrate; relies on the
    # existing SHORT-bias + conviction gate. No global gate weakened.
    "XRP": SymbolOverrides(
        max_leverage=10.0,
        risk_per_trade=0.05,
        volatility_profile="medium",
    ),
    # POPCAT: NEW memecoin symbol (2026-07-14), n=0 history. Even more conservative than
    # XRP — memecoins whip hard, so lowest leverage cap (5x), risk_per_trade=0.03 (below XRP's
    # 0.05, ~1/3 of global), wide ATR stops (like HYPE) to survive mean-reversion vol.
    # Tightens until n>=10 trades calibrate. No global gate weakened.
    "POPCAT": SymbolOverrides(
        max_leverage=5.0,
        risk_per_trade=0.03,
        volatility_profile="high",
        atr_mult_sl=2.2,
        atr_mult_tp1=3.3,
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
# This table is the n<13 FALLBACK for sl_mult — get_regime_sl_tp() below layers a
# live, SYMMETRIC (widen AND narrow) SL adjustment from data/trade_ledger.csv
# SL-hit-rate on top of these values when n>=13. tp1_mult/tp2_mult have no live
# path yet (would need trade_dna TP1-hit-rate/MFE data — out of scope for this
# file); they remain static.
# LIVING VALUES refresh 2026-07-15 — comments now show REALIZED stats from the
# ledger (paper_trades trades_*.csv, 265 clean closes; SL exits overall: n=91,
# net -$690.83, avg -$7.59/tr):
REGIME_SL_TP_SCALARS = {
    "trending_bull":    {"sl_mult": 1.2, "tp1_mult": 1.3, "tp2_mult": 1.5},
    "trending_bear":    {"sl_mult": 1.1, "tp1_mult": 1.2, "tp2_mult": 1.4},
    "trend":            {"sl_mult": 1.15, "tp1_mult": 1.25, "tp2_mult": 1.4},
    # trending family (trending+trend+trending_bull+trending_bear) n=20, WR 15%,
    # -$506 total (avg -$25/tr) — NOT "52% WR +$118" as previously claimed; the
    # wide TPs granted here are stale, kept only as the n<13 fallback pending a
    # live TP path (see comment above).
    "trending":         {"sl_mult": 1.2, "tp1_mult": 1.3, "tp2_mult": 1.5},
    # consolidation: n=84, avg -$3.8/tr, WR 46%, SL-hit 50% — mild loser, not "0% WR"
    "consolidation":    {"sl_mult": 0.85, "tp1_mult": 0.9, "tp2_mult": 0.85},
    # range/ranging: n=23, SL-hit 52%, WR 35%, avg -$11.4/tr — 52% is BELOW the
    # 65% SL-hit target, so the old "94% SL hits, need wider stop" justification
    # for sl=1.4 is stale; the live symmetric narrowing in get_regime_sl_tp()
    # will pull this down toward the target once n>=13 (already satisfied here).
    "range":            {"sl_mult": 1.4, "tp1_mult": 0.8, "tp2_mult": 0.85},
    "ranging":          {"sl_mult": 1.4, "tp1_mult": 0.8, "tp2_mult": 0.85},  # same as range
    "high_volatility":  {"sl_mult": 1.4, "tp1_mult": 1.2, "tp2_mult": 2.0},
    "panic":            {"sl_mult": 1.5, "tp1_mult": 0.6, "tp2_mult": 0.6},
    # illiquid: the "n=57, 82% SL hits" basis for sl=1.5 no longer exists in the
    # live ledger (n=3 now) — kept only as the n<13 fallback; too sparse to
    # re-validate or correct with current data.
    "low_liquidity":    {"sl_mult": 1.5, "tp1_mult": 0.75, "tp2_mult": 0.75},
    "illiquid":         {"sl_mult": 1.5, "tp1_mult": 0.75, "tp2_mult": 0.75},  # same as low_liquidity
    # "unknown" intentionally omitted — pass through base values unchanged
}


# Regime-aware risk sizing: bet bigger where edge is proven, smaller where it isn't.
# This table is the n<13 FALLBACK ONLY — get_regime_risk_mult() below computes
# an EV-aware live multiplier from data/trade_ledger.csv (regime_1h, n>=13) and
# blends toward it, replacing the WR-only mapping that used to contradict the
# ledger (e.g. consolidation 46% WR was up-sized to 0.90 despite realized avg
# -$4.67/tr). LIVING VALUES refresh 2026-07-15 — comments now show REALIZED
# avg net PnL/trade (pnl-fee) from data/trade_ledger.csv (216 clean rows):
REGIME_RISK_MULTIPLIERS = {
    "trending_bear":    1.0,    # BEST REGIME: n=15, +$81.70/tr, 33% WR — FULL SIZE
    "trending_bull":    0.55,   # n=9, 33% WR, -$29.46/tr realized — reduced pending
                                 # n>=13 live signal; 0.55 = _wr_to_risk_mult(0.33).
                                 # Stale claim was "+$45, 67% WR, PF=4546" (Apr-2026
                                 # snapshot); realized ledger contradicts it.
    "trending":         0.50,   # n=17, 17.6% WR, -$8.28/tr — net loser, not "52% WR +$118"
    "high_volatility":  0.85,   # n=12, +$23.93/tr — small sample but net-positive
    "illiquid":         0.50,   # 28% WR n=57 -$83 — down from 0.70: live data proves losing regime
    "trend":            0.50,   # TRAP: -$200, 18% WR, PF=0.15 — weak ADX, treat like range
    "range":            0.45,   # n=33, -$10.29/tr — consistent loser
    "ranging":          0.45,   # same as range
    "consolidation":    0.30,   # n=89, 46.1% WR, -$4.67/tr — mild loser (NOT "0% WR
                                 # DISASTER" as previously claimed; still minimum size
                                 # since EV is negative)
    "panic":            0.50,   # No live data — cautious
    "low_liquidity":    0.40,   # Canonical name for illiquid — minimal
    "news_dislocation": 0.50,   # Unpredictable — cautious
    "unknown":          0.45,   # n=34, -$1.98/tr — losing regime, reduced from 0.50
}


# Symbol-specific risk scaling — LIVING VALUE (2026-07-15): n>=13 symbols are
# now computed LIVE from the ledger via feedback.live_edge.get_symbol_mult
# (avg net PnL/trade, both sides). This dict is ONLY the n<13 fallback, used
# when live evidence is insufficient or DATA_DRIVEN_SYMBOL_MULT is off.
# Fallback values as of 2026-07-15 ledger (paper_trades/*.csv, net=pnl-fee):
# ETH n=62 +$10.87/tr (52% WR) — best symbol
# BTC n=63 +$6.59/tr (44% WR)
# SOL n=59 +$4.36/tr (58% WR)
# XRP n=44 -$1.90/tr (68% WR — WR misleading, PnL/trade is negative)
# HYPE n=37 -$15.20/tr — worst symbol, proven net loser
SYMBOL_RISK_MULTIPLIERS = {
    "ETH":  1.0,   # Best symbol by PnL/trade. Full size.
    "BTC":  0.90,  # Solid but needs leverage control (<=7x).
    "SOL":  0.80,  # High variance. Great in trending_bear, bad elsewhere.
    "HYPE": 0.40,  # PROVEN NET LOSER: n=37, -$15.20/tr — worst symbol on the ledger.
    "XRP":  0.50,  # n=44, -$1.90/tr net despite 68% WR (WR is misleading here;
                   # payoff is negative) — sized below HYPE's old floor accordingly.
    "POPCAT": 0.50,  # NEW memecoin (2026-07-14), n=0: no edge data yet.
                     # Keeps uncalibrated POPCAT trades tiny until n>=13 validates edge.
}

# NOTE (2026-07-15): SYMBOL_SIDE_RISK_MULTIPLIERS was deleted here — it was a
# stale 2026-03-30 backtest table that inverted the realized ledger edge
# (penalized ETH_SELL, the best live edge at +$24.45/tr, to 0.70x; only cut
# HYPE_BUY, the worst at -$38.94/tr, to 0.70x). The governing live path is
# feedback.live_edge.get_side_mult (ledger-computed avg net PnL/trade, n>=13),
# with neutral 1.0 fallback below when live evidence is insufficient.

# Per-symbol lead-lag configuration: empirical lag times and correlations.
# Used by LeadLagBoostEngine to generate confidence boosts for follower assets.
# lag_minutes: (min, max) expected lag behind BTC
# correlation: empirical correlation coefficient (0-1)
# beta: follower amplification factor (1.2 = follower moves 1.2x BTC's %)
# boost_cap: maximum confidence boost for this symbol from lead-lag
# LIVING VALUES note (2026-07-15): boost_cap here is a STATIC, side-blind cap —
# per-close net (pnl-fee) from paper_trades/*.csv actually ranks ETH_SHORT
# +$20.37/tr (n=36, the single best slice) ABOVE SOL_SHORT +$7.65/tr (n=39),
# the opposite of this table's SOL(12) > ETH(10) ranking, and the old "ETH
# follows faster, less edge" comment below was factually wrong — it does not.
# ALL long slices are realized net losers (worst: HYPE_BUY -$34.36/tr, n=17).
# Making boost_cap live/side-aware (ledger-derived, zeroed for net-loser
# slices) belongs in execution/cross_asset_alert.py (out of scope for this
# file); these numbers remain the fallback shell. lead_lag_max_boost=12.0
# above is the absolute safety ceiling and is intentionally left untouched.
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
        "boost_cap": 10.0,            # NOTE: realized ETH_SHORT (+$20.37/tr, n=36)
                                        # is the ledger's BEST slice — this cap is
                                        # NOT justified by "less edge" (see note above).
    },
    "HYPE": {
        "lag_minutes": (15, 45),       # HYPE less predictable
        "correlation": 0.44,
        "beta": 1.50,
        "boost_cap": 5.0,             # Low cap: weak correlation. Still non-zero
                                        # despite HYPE_BUY being the ledger's worst
                                        # slice (-$34.36/tr, n=17) — side-blind cap.
    },
}


# NOTE (2026-07-15): SETUP_OPTIMAL_EXITS was deleted here — it was a dormant
# 2026-?? table never consumed by any live decision path (verified zero readers),
# and its "edge" labels were inverted vs the realized ledger: it labeled ETH_BUY
# and HYPE_BUY tier2 "edge" while both are realized-negative (HYPE_BUY worst at
# -$34.36/tr), and it omitted ETH_SELL, the actual best edge at +$20.37/tr.
# Exit behavior stays governed by the live paths: position_manager's trade-profile/
# TP1/trailing state machine plus the LLM Exit Agent. If per-setup exit profiles
# are wanted, compute them live from paper_trades/*.csv per symbol_side net PnL
# (n>=13), like feedback.live_edge.get_side_mult — never a frozen table.


def get_lead_lag_config(symbol: str) -> dict:
    """Return lead-lag configuration for a symbol. Returns empty dict if not configured."""
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    return LEAD_LAG_SYMBOL_CONFIG.get(base, {})


def get_symbol_risk_mult(symbol: str) -> float:
    """Return position-size multiplier for the given symbol.

    LIVING VALUE (2026-07-15): when DATA_DRIVEN_SYMBOL_MULT is on (default), this
    is computed LIVE from the ledger (avg net PnL/trade, both sides, n>=13) via
    feedback.live_edge.get_symbol_mult — the same pattern as
    get_symbol_side_risk_mult. Live mult is clamped to [0.30, 1.0]: it can only
    ever be as-safe-or-safer than full size, never a boost above the static cap.
    Falls back to the static SYMBOL_RISK_MULTIPLIERS table when live evidence is
    insufficient (n<13), the symbol is unrecognized, or the flag is off.
    Revert: DATA_DRIVEN_SYMBOL_MULT=false -> legacy static SYMBOL_RISK_MULTIPLIERS.
    """
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    static_mult = SYMBOL_RISK_MULTIPLIERS.get(base, 0.70)
    if os.getenv("DATA_DRIVEN_SYMBOL_MULT", "true").strip().lower() in ("1", "true", "yes"):
        try:
            from feedback.live_edge import get_symbol_mult as _dd_symbol_mult
            _live = _dd_symbol_mult(base)
            if _live is not None:
                return round(max(0.30, min(1.0, _live)), 3)
        except Exception as e:
            logger.warning(f"[SYMBOL-MULT] live_edge lookup failed for {base}: {e}")
    return static_mult


def get_symbol_side_risk_mult(symbol: str, side: str) -> float:
    """Return position-size multiplier for a specific symbol+side combo.

    LIVING VALUE (2026-07-14): when DATA_DRIVEN_SIDE_MULT is on (default), this is
    computed LIVE from the ledger (PnL/trade, n>=13) via feedback.live_edge —
    replacing the stale 2026-03-30 hardcoded table (deleted 2026-07-15), which had
    it BACKWARDS (penalized ETH_SELL, the best live edge, and under-penalized
    HYPE_BUY, the worst). Neutral 1.0 when live evidence is insufficient (n<13)
    or the DATA_DRIVEN_SIDE_MULT flag is off — no pre-decided bias.
    Revert: DATA_DRIVEN_SIDE_MULT=false -> neutral 1.0 (legacy hardcoded table removed).
    """
    base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
    # Normalize side: LONG->BUY, SHORT->SELL for consistent lookup
    normalized_side = "BUY" if side.upper() in ("BUY", "LONG") else "SELL"
    try:
        from feedback.live_edge import enabled as _dd_enabled, get_side_mult as _dd_mult
        if _dd_enabled():
            _live = _dd_mult(base, normalized_side)
            return _live if _live is not None else 1.0
    except Exception as e:
        logger.warning(f"[SYMBOL-SIDE-MULT] live_edge lookup failed for {base}_{normalized_side}: {e}")
    return 1.0


_REGIME_LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "trade_ledger.csv")
_regime_ledger_cache = {"mtime": None, "stats": {}}
# Synthetic/test entry prices seeded by test fixtures — exclude from live stats.
_TEST_ENTRY_PRICES = (100.0, 150.0, 50000.0)


def _get_regime_ledger_ev(regime: str) -> Optional[dict]:
    """LIVING VALUE (2026-07-15): live per-regime expectancy from
    data/trade_ledger.csv (regime_1h, net_pnl), n>=13 gate. Excludes TEST
    symbols and synthetic entry prices used by test fixtures. Self-contained
    (reads the ledger directly) so it does not depend on trade_dna, which
    undercounts some regimes (e.g. trending_bull n=4 in trade_dna vs n=9 here).
    Returns {"n": int, "avg_net": float} or None if unavailable/insufficient.
    """
    try:
        mtime = os.path.getmtime(_REGIME_LEDGER_PATH)
    except OSError:
        return None
    if _regime_ledger_cache["mtime"] != mtime:
        stats = {}
        try:
            import csv as _csv
            with open(_REGIME_LEDGER_PATH, newline="", encoding="utf-8", errors="ignore") as f:
                for row in _csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper()
                    if "TEST" in sym:
                        continue
                    try:
                        entry_price = float(row.get("entry_price") or 0)
                    except (TypeError, ValueError):
                        entry_price = 0.0
                    if entry_price in _TEST_ENTRY_PRICES:
                        continue
                    try:
                        net = float(row.get("net_pnl"))
                    except (TypeError, ValueError):
                        continue
                    reg = (row.get("regime_1h") or "unknown").strip().lower() or "unknown"
                    d = stats.setdefault(reg, {"n": 0, "sum": 0.0})
                    d["n"] += 1
                    d["sum"] += net
        except Exception:
            stats = {}
        _regime_ledger_cache["mtime"] = mtime
        _regime_ledger_cache["stats"] = {
            k: {"n": v["n"], "avg_net": v["sum"] / v["n"]} for k, v in stats.items() if v["n"] > 0
        }
    return _regime_ledger_cache["stats"].get((regime or "unknown").lower())


def _ev_to_risk_mult(avg_net: float) -> float:
    """Map realized avg net PnL/trade (EV) to a risk multiplier.

    Replaces the deleted WR-only _wr_to_risk_mult: win rate is anti-correlated
    with expectancy in this ledger (e.g. consolidation 46% WR but -$4.67/tr,
    XRP 68% WR but -$1.90/tr), so a WR-keyed curve up-sized net losers. EV-keyed
    instead. Never sizes above 1.0 (no boosting above the static full-size cap);
    floors at 0.45.
    """
    if avg_net > 5.0:
        return 1.0
    if avg_net > 0.0:
        return 0.85
    if avg_net > -5.0:
        return 0.60
    return 0.45


def get_regime_risk_mult(regime: str) -> float:
    """Return position-size multiplier for the given regime.

    LIVING VALUE (2026-07-15): the live path is now EV-based (avg realized net
    PnL/trade from data/trade_ledger.csv, n>=13 — lowered from n>=15 per the
    LIVING VALUES mandate), replacing the WR-only mapping that contradicted the
    ledger (e.g. consolidation 46% WR was up-sized to 0.90 despite realized avg
    -$4.67/tr, n=89). Blends toward full live trust by n=50. Falls back to the
    static REGIME_RISK_MULTIPLIERS table when n<13 or the ledger is unavailable.
    Clamped to [0.30, 1.0] — this only ever reduces size, never boosts above the
    static full-size ceiling.
    """
    static_mult = REGIME_RISK_MULTIPLIERS.get(regime, 0.8)
    try:
        stats = _get_regime_ledger_ev(regime)
        if stats and stats["n"] >= 13:
            live_mult = _ev_to_risk_mult(stats["avg_net"])
            # Blend: weight live data more as n grows (full trust at n=50+)
            blend = min(1.0, (stats["n"] - 13) / 35)
            blended = static_mult * (1 - blend) + live_mult * blend
            return round(max(0.30, min(1.0, blended)), 3)
    except Exception:
        pass
    return static_mult


def _get_regime_sl_hit_rate_ledger(regime: str) -> Optional[dict]:
    """LIVING VALUE (2026-07-15): live per-regime SL-hit-rate from
    data/trade_ledger.csv (regime_1h, exit_type), n>=13 gate. Same
    TEST-symbol/synthetic-entry-price exclusions as _get_regime_ledger_ev.
    Self-contained ledger read, used only to NARROW sl_scalar (the existing
    DynamicThresholds path stays as the widen-only source, unchanged).
    Returns {"n": int, "sl_hit_rate": float} or None.
    """
    try:
        mtime = os.path.getmtime(_REGIME_LEDGER_PATH)
    except OSError:
        return None
    cache = _get_regime_sl_hit_rate_ledger.__dict__.setdefault(
        "_cache", {"mtime": None, "stats": {}}
    )
    if cache["mtime"] != mtime:
        stats = {}
        try:
            import csv as _csv
            with open(_REGIME_LEDGER_PATH, newline="", encoding="utf-8", errors="ignore") as f:
                for row in _csv.DictReader(f):
                    sym = str(row.get("symbol", "")).upper()
                    if "TEST" in sym:
                        continue
                    try:
                        entry_price = float(row.get("entry_price") or 0)
                    except (TypeError, ValueError):
                        entry_price = 0.0
                    if entry_price in _TEST_ENTRY_PRICES:
                        continue
                    reg = (row.get("regime_1h") or "unknown").strip().lower() or "unknown"
                    d = stats.setdefault(reg, {"n": 0, "sl": 0})
                    d["n"] += 1
                    if str(row.get("exit_type", "")).strip().upper() == "SL":
                        d["sl"] += 1
        except Exception:
            stats = {}
        cache["mtime"] = mtime
        cache["stats"] = {
            k: {"n": v["n"], "sl_hit_rate": v["sl"] / v["n"]} for k, v in stats.items() if v["n"] > 0
        }
    return cache["stats"].get((regime or "unknown").lower())


def get_regime_sl_tp(regime: str, base_sl_mult: float, base_tp1_mult: float,
                     base_tp2_mult: float) -> tuple:
    """Apply regime-conditional scaling to SL/TP multipliers.

    Blends static REGIME_SL_TP_SCALARS with a live data-driven SL boost from
    DynamicThresholds. When a regime's SL hit rate in trade_dna exceeds the
    system-optimal ~72%, the SL scalar is widened proportionally so stops
    adapt to actual market noise levels rather than staying frozen at config values.

    LIVING VALUES fix 2026-07-15: the widen-only live path above could never
    self-correct downward (a stale "94% SL hits" justification could persist
    forever even after the live rate dropped, e.g. range is now 52% n=23,
    below the 65% target). This is now SYMMETRIC — a second, self-contained
    ledger read (data/trade_ledger.csv) narrows sl_scalar proportionally when
    the live SL-hit-rate is well below target (n>=13), clamped to the table's
    existing safety envelope [0.85, 1.5] so stops never widen/narrow past the
    historically validated range. TP1/TP2 have no live path yet (would need
    trade_dna TP1-hit-rate/MFE data — out of scope for this file).

    Returns (adjusted_sl_mult, adjusted_tp1_mult, adjusted_tp2_mult).
    """
    scalars = REGIME_SL_TP_SCALARS.get(regime)
    if scalars is None:
        return (base_sl_mult, base_tp1_mult, base_tp2_mult)

    sl_scalar = scalars["sl_mult"]

    # Layer dynamic SL boost from live SL-hit-rate data (trade_dna, widen-only)
    try:
        from llm.dynamic_thresholds import get_dynamic_thresholds
        dynamic_boost = get_dynamic_thresholds().get_dynamic_sl_boost(regime, sl_scalar)
        if dynamic_boost > 0:
            sl_scalar = sl_scalar + dynamic_boost
    except Exception:
        pass  # Never block a trade on a boost computation error

    # Symmetric narrowing from the ledger when SL-hit-rate is well below the
    # 65% target (self-contained; never raises above the widen path's result).
    try:
        led = _get_regime_sl_hit_rate_ledger(regime)
        if led and led["n"] >= 13 and led["sl_hit_rate"] < 0.58:
            blend = min(1.0, (led["n"] - 13) / 35)
            sl_scalar -= (0.65 - led["sl_hit_rate"]) * 0.6 * blend
    except Exception:
        pass  # Never block a trade on a boost computation error

    # Clamp to the table's existing safety envelope
    sl_scalar = max(0.85, min(1.5, sl_scalar))

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
