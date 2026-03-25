"""
Manual Sniper Signal configuration.

Two modes:
- AGGRESSIVE: $100 account scaling mode. Max leverage, max conviction only.
  Only fires on absolute best signals. Goal: compound small account fast.
- STANDARD: $10k+ account mode. More signals, moderate leverage.

Proven edges driving these defaults:
- HYPE BUY: 85% WR, avg +4.68% per trade
- 6-12h holds: 59.7% WR (best window)
- 80-89% confidence: PF=17-22 (sweet spot)
- 3-agree consensus: $234-$582 per trade avg
- Consolidation regime: 47% WR, PF=2.1
"""

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


@dataclass
class ManualSniperConfig:
    """Configuration for manual sniper signals."""

    # Enable/disable
    enabled: bool = field(default_factory=lambda: _env_bool("MANUAL_SNIPER_ENABLED", True))

    # ── Account mode ──
    # "aggressive" = $100 scaling mode (few signals, max leverage, max size)
    # "standard"   = $10k+ mode (more signals, moderate leverage)
    mode: str = field(default_factory=lambda: _env("MANUAL_MODE", "aggressive"))

    # Account (updated live from bot equity or set manually)
    equity: float = field(default_factory=lambda: _env_float("MANUAL_EQUITY", 100.0))
    daily_target: float = field(default_factory=lambda: _env_float("MANUAL_DAILY_TARGET", 20.0))
    # $20/day on $100 = 20%/day early, scales down as account grows.
    # Target: $100 → $1000 in 45 days = ~5.2% daily compound growth.
    # 1 solid HYPE BUY per day at $20-50 profit achieves this.

    # ── Signal quality filters ──
    # Aggressive mode: only the absolute best signals
    min_confidence: float = field(default_factory=lambda: _env_float("MANUAL_MIN_CONFIDENCE", 78.0))
    min_num_agree: int = field(default_factory=lambda: _env_int("MANUAL_MIN_AGREE", 2))
    # Premium/Sniper thresholds
    premium_min_confidence: float = field(default_factory=lambda: _env_float("MANUAL_PREMIUM_CONFIDENCE", 80.0))
    premium_min_agree: int = field(default_factory=lambda: _env_int("MANUAL_PREMIUM_AGREE", 2))
    # Was 3 — lowered to 2 based on live data analysis:
    # 80%+ conf with 3 agree = ~2 signals/day (too thin)
    # 80%+ conf with 2 agree = ~10 signals/day (after dedup = 3-5 actionable)
    min_rr: float = field(default_factory=lambda: _env_float("MANUAL_MIN_RR", 1.2))

    # ── Leverage tiers ──
    # Aggressive mode: higher across the board because we're watching the screen
    leverage_tier_1: float = field(default_factory=lambda: _env_float("MANUAL_LEV_T1", 10.0))  # STANDARD tier
    leverage_tier_2: float = field(default_factory=lambda: _env_float("MANUAL_LEV_T2", 15.0))  # PREMIUM base
    leverage_tier_3: float = field(default_factory=lambda: _env_float("MANUAL_LEV_T3", 20.0))  # PREMIUM high conf
    leverage_tier_4: float = field(default_factory=lambda: _env_float("MANUAL_LEV_T4", 25.0))  # SNIPER
    leverage_tier_5: float = field(default_factory=lambda: _env_float("MANUAL_LEV_T5", 25.0))  # MAX (90%+ conf)
    max_leverage: float = field(default_factory=lambda: _env_float("MANUAL_MAX_LEVERAGE", 25.0))

    # ── Risk per trade (% of equity) ──
    # Aggressive on $100: we NEED to size up on best signals to compound
    # SNIPER = our 85% WR, 3-agree signals. Losing 10% of $100 = $10. Acceptable.
    # But winning at 20-25x on a 2% move = $40-50. That's the math.
    risk_pct_standard: float = field(default_factory=lambda: _env_float("MANUAL_RISK_STANDARD", 0.05))   # 5% ($5 on $100)
    risk_pct_premium: float = field(default_factory=lambda: _env_float("MANUAL_RISK_PREMIUM", 0.08))     # 8% ($8 on $100)
    risk_pct_sniper: float = field(default_factory=lambda: _env_float("MANUAL_RISK_SNIPER", 0.10))       # 10% ($10 on $100)

    # ── Preferred symbols (proven edges) ──
    preferred_symbols: list = field(default_factory=lambda: _env(
        "MANUAL_PREFERRED_SYMBOLS", "HYPE,BTC,SOL"
    ).split(","))

    # Preferred regimes (from backtesting data)
    strong_regimes: list = field(default_factory=lambda: [
        "consolidation", "trend", "trending_bull", "trending_bear"
    ])
    weak_regimes: list = field(default_factory=lambda: [
        "panic", "high_volatility", "unknown"
    ])

    # ── Hold time targets ──
    target_hold_hours_scalp: float = field(default_factory=lambda: _env_float("MANUAL_HOLD_SCALP", 2.0))
    target_hold_hours_swing: float = field(default_factory=lambda: _env_float("MANUAL_HOLD_SWING", 8.0))

    # ── Telegram config ──
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env("MANUAL_TELEGRAM_CHAT_ID",
                                                                _env("TELEGRAM_CHAT_ID", "")))

    # ── Dedup / rate limiting ──
    # Cooldown between alerts for same symbol+side (prevent spam)
    min_alert_gap_s: int = field(default_factory=lambda: _env_int("MANUAL_ALERT_GAP_S", 300))
    # Only send truly distinct signals (dedup by symbol+side+confidence_band)
    dedup_window_s: int = field(default_factory=lambda: _env_int("MANUAL_DEDUP_WINDOW_S", 600))

    # ── Daily tracking ──
    # Aggressive mode: only 3-5 best signals per day. Quality over quantity.
    max_daily_signals: int = field(default_factory=lambda: _env_int("MANUAL_MAX_DAILY_SIGNALS", 5))

    # ── Account growth tracking ──
    # Track running equity to adjust sizing as account grows
    compound_sizing: bool = field(default_factory=lambda: _env_bool("MANUAL_COMPOUND_SIZING", True))

    # ── Expanded setups (opt-in) ──
    # Enable research-identified setups (BTC SHORT >=90, BTC LONG 70-80) for paper validation
    # Set MANUAL_EXPANDED_SETUPS=true to enable
    expanded_setups: bool = field(default_factory=lambda: _env_bool("MANUAL_EXPANDED_SETUPS", False))
