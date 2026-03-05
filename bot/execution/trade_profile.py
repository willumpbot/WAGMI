"""
Trade Classification Layer.

Classifies every trade into a profile (SCALP, MEDIUM, TREND, REGIME)
and derives exit parameters from that profile. This is the core architectural
layer that makes exits match entries.

Every Position carries a TradeProfile that drives:
- TP1 distance (ATR multiples)
- TP1 close percentage
- SL distance (ATR multiples)
- Trailing style and parameters
- Expected holding time

Strategy -> entry_type mapping:
- regime_trend       -> TREND
- multi_tier_quality -> TREND
- monte_carlo_zones  -> MEDIUM
- confidence_scorer  -> MEDIUM
- (future) microstructure / fast_ml -> SCALP
- (future) volatility_regime -> REGIME (modifier, not standalone)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.execution.trade_profile")


# ── Entry types ──────────────────────────────────────────

SCALP = "SCALP"
MEDIUM = "MEDIUM"
TREND = "TREND"
REGIME = "REGIME"

ALL_ENTRY_TYPES = {SCALP, MEDIUM, TREND, REGIME}


# ── Strategy -> entry type mapping ────────────────────────

STRATEGY_ENTRY_TYPE = {
    "regime_trend": TREND,
    "multi_tier_quality": TREND,
    "monte_carlo_zones": MEDIUM,
    "confidence_scorer": MEDIUM,
    # Future strategies:
    # "microstructure": SCALP,
    # "fast_ml": SCALP,
    # "volatility_regime": REGIME,
}

STRATEGY_INTENT = {
    "regime_trend": "higher timeframe trend alignment",
    "multi_tier_quality": "multi-signal, high-quality trend setup",
    "monte_carlo_zones": "zone-based, medium horizon",
    "confidence_scorer": "ML-driven scoring, medium horizon",
}


# ── Env var helper ────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    """Read a float from environment, fall back to default."""
    import os
    val = os.environ.get(name)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


# ── Exit profile parameters per entry type ───────────────
# These are the recommended defaults. Regime and volatility can modify them.
# Override any parameter via env var: PROFILE_{TYPE}_{PARAM}
# e.g., PROFILE_SCALP_TP1_PCT=0.85, PROFILE_MEDIUM_SL_ATR=0.80

@dataclass
class ExitParams:
    """Exit parameters derived from entry_type + regime + volatility."""
    tp1_atr_mult: float      # TP1 distance in ATR multiples
    tp2_atr_mult: float      # TP2 distance in ATR multiples
    sl_atr_mult: float       # SL distance in ATR multiples
    tp1_close_pct: float     # fraction to close at TP1
    trailing_style: str      # "tight", "medium", "loose", "none"
    # Trailing tighten curve: factor shrinks from start->end as price->TP2
    trailing_tighten_start: float  # initial tighten factor (wider)
    trailing_tighten_end: float    # final tighten factor (tighter)
    # Profit lock floor: minimum % of peak move to guarantee
    floor_progress_start: float    # progress % before floor kicks in
    floor_lock_start: float        # initial floor lock %
    floor_lock_max: float          # maximum floor lock %


# Conservative defaults per entry type.
# Safety-first: when in doubt, tighter exits.
def _build_profile(prefix: str, defaults: dict) -> ExitParams:
    """Build ExitParams with env var overrides for the given profile prefix."""
    return ExitParams(
        tp1_atr_mult=_env_float(f"PROFILE_{prefix}_TP1_ATR", defaults["tp1_atr"]),
        tp2_atr_mult=_env_float(f"PROFILE_{prefix}_TP2_ATR", defaults["tp2_atr"]),
        sl_atr_mult=_env_float(f"PROFILE_{prefix}_SL_ATR", defaults["sl_atr"]),
        tp1_close_pct=_env_float(f"PROFILE_{prefix}_TP1_PCT", defaults["tp1_pct"]),
        trailing_style=defaults["trailing"],
        trailing_tighten_start=_env_float(f"PROFILE_{prefix}_TRAIL_START", defaults["trail_start"]),
        trailing_tighten_end=_env_float(f"PROFILE_{prefix}_TRAIL_END", defaults["trail_end"]),
        floor_progress_start=_env_float(f"PROFILE_{prefix}_FLOOR_PROGRESS", defaults["floor_progress"]),
        floor_lock_start=_env_float(f"PROFILE_{prefix}_FLOOR_START", defaults["floor_start"]),
        floor_lock_max=_env_float(f"PROFILE_{prefix}_FLOOR_MAX", defaults["floor_max"]),
    )

_BASE_PROFILES: Dict[str, ExitParams] = {
    SCALP: _build_profile("SCALP", {
        "tp1_atr": 0.5, "tp2_atr": 1.0, "sl_atr": 0.4, "tp1_pct": 0.90,
        "trailing": "tight", "trail_start": 0.80, "trail_end": 0.50,
        "floor_progress": 0.2, "floor_start": 0.40, "floor_max": 0.75,
    }),
    MEDIUM: _build_profile("MEDIUM", {
        "tp1_atr": 1.0, "tp2_atr": 2.0, "sl_atr": 0.75, "tp1_pct": 0.65,  # was 0.50
        "trailing": "medium", "trail_start": 0.60, "trail_end": 0.30,
        "floor_progress": 0.35, "floor_start": 0.25, "floor_max": 0.60,
    }),
    TREND: _build_profile("TREND", {
        "tp1_atr": 1.5, "tp2_atr": 3.0, "sl_atr": 1.0, "tp1_pct": 0.50,  # was 0.35
        "trailing": "loose", "trail_start": 0.50, "trail_end": 0.25,
        "floor_progress": 0.35, "floor_start": 0.25, "floor_max": 0.55,
    }),
    REGIME: _build_profile("REGIME", {
        "tp1_atr": 1.2, "tp2_atr": 2.5, "sl_atr": 0.8, "tp1_pct": 0.50,
        "trailing": "medium", "trail_start": 0.60, "trail_end": 0.30,
        "floor_progress": 0.3, "floor_start": 0.30, "floor_max": 0.60,
    }),
}


# ── TradeProfile ─────────────────────────────────────────

@dataclass
class TradeProfile:
    """
    Full trade classification attached to every position.
    Drives exit logic, risk, and expectations.
    """
    entry_type: str              # SCALP, MEDIUM, TREND, REGIME
    entry_reasons: List[str]     # which strategies fired
    primary_driver: str          # which strategy was dominant
    confidence: float            # ensemble confidence at entry
    regime: str                  # "trending", "ranging", "volatile", "illiquid"
    volatility_band: str         # "low", "medium", "high"
    timeframe_bias: str          # "short", "medium", "long"

    # Derived exit parameters
    exit_params: ExitParams = field(default_factory=lambda: _BASE_PROFILES[MEDIUM])

    # Computed absolute prices (filled by classify_trade)
    recommended_tp1: float = 0.0
    recommended_tp2: float = 0.0
    recommended_sl: float = 0.0

    expected_holding_time: str = "medium"  # "very_short", "short", "medium", "long"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging."""
        return {
            "entry_type": self.entry_type,
            "entry_reasons": self.entry_reasons,
            "primary_driver": self.primary_driver,
            "confidence": round(self.confidence, 1),
            "regime": self.regime,
            "volatility_band": self.volatility_band,
            "timeframe_bias": self.timeframe_bias,
            "tp1_close_pct": self.exit_params.tp1_close_pct,
            "trailing_style": self.exit_params.trailing_style,
            "expected_holding_time": self.expected_holding_time,
            "notes": self.notes,
        }


# ── Classification logic ─────────────────────────────────

def _determine_primary_driver(
    strategies_agree: List[str],
    individual_confidences: Dict[str, float],
    strategy_weights: Dict[str, float],
) -> str:
    """Pick the dominant strategy by weight * confidence."""
    if not strategies_agree:
        return "unknown"

    best = None
    best_score = -1.0
    for strat in strategies_agree:
        w = strategy_weights.get(strat, 1.0)
        c = individual_confidences.get(strat, 50.0)
        score = w * c
        if score > best_score:
            best_score = score
            best = strat
    return best or strategies_agree[0]


def _determine_entry_type(primary_driver: str, strategies_agree: List[str]) -> str:
    """Classify entry_type from primary driver.
    If all strategies are TREND -> TREND.
    If mixed TREND+MEDIUM -> MEDIUM (conservative: don't widen exits for mixed signals)."""
    primary_type = STRATEGY_ENTRY_TYPE.get(primary_driver, MEDIUM)

    # Check if unanimous
    types = [STRATEGY_ENTRY_TYPE.get(s, MEDIUM) for s in strategies_agree]
    unique_types = set(types)

    if len(unique_types) == 1:
        return unique_types.pop()

    # Mixed: use primary driver's type, but if mixing TREND with MEDIUM,
    # be conservative and use MEDIUM (tighter exits are safer)
    if SCALP in unique_types:
        return SCALP  # any SCALP signal means treat as SCALP
    if TREND in unique_types and MEDIUM in unique_types:
        # Conservative choice: MEDIUM unless primary driver is TREND and dominant
        return primary_type

    return primary_type


def _determine_regime(signal_metadata: Dict[str, Any]) -> str:
    """Detect market regime from signal metadata."""
    trend_adj = signal_metadata.get("trend_adjustment", 0)
    vol_ratio = signal_metadata.get("volume_ratio", 1.0)

    # Strong trend alignment bonus (negative trend_adj = aligned) -> trending
    if trend_adj <= -5:
        return "trending"
    # Strong counter-trend penalty -> ranging/choppy
    if trend_adj >= 10:
        return "ranging"
    # Low volume -> illiquid
    if vol_ratio < 0.5:
        return "illiquid"
    # Moderate trend -> trending
    if trend_adj < 0:
        return "trending"

    return "ranging"


def _determine_volatility_band(atr: float, price: float) -> str:
    """Classify volatility from ATR/price ratio."""
    if price <= 0 or atr <= 0:
        return "medium"
    vol_pct = (atr / price) * 100
    if vol_pct < 1.5:
        return "low"
    elif vol_pct > 3.0:
        return "high"
    return "medium"


def _holding_time_for_type(entry_type: str) -> str:
    return {
        SCALP: "very_short",
        MEDIUM: "short",
        TREND: "medium",
        REGIME: "long",
    }.get(entry_type, "medium")


def _timeframe_bias_for_type(entry_type: str) -> str:
    return {
        SCALP: "short",
        MEDIUM: "medium",
        TREND: "long",
        REGIME: "long",
    }.get(entry_type, "medium")


def _adjust_params_for_regime(params: ExitParams, regime: str, volatility: str) -> ExitParams:
    """Modify exit params based on regime and volatility context.
    Returns a new ExitParams (does not mutate the original)."""
    # Start with a copy
    p = ExitParams(
        tp1_atr_mult=params.tp1_atr_mult,
        tp2_atr_mult=params.tp2_atr_mult,
        sl_atr_mult=params.sl_atr_mult,
        tp1_close_pct=params.tp1_close_pct,
        trailing_style=params.trailing_style,
        trailing_tighten_start=params.trailing_tighten_start,
        trailing_tighten_end=params.trailing_tighten_end,
        floor_progress_start=params.floor_progress_start,
        floor_lock_start=params.floor_lock_start,
        floor_lock_max=params.floor_lock_max,
    )

    # Regime adjustments
    if regime == "trending":
        # Let winners run: widen TP2, lower TP1%, loosen trailing
        p.tp2_atr_mult *= 1.2
        p.tp1_close_pct = max(0.20, p.tp1_close_pct - 0.10)
        p.trailing_tighten_end = max(0.20, p.trailing_tighten_end - 0.05)
    elif regime == "ranging":
        # Take profits quicker: tighten TP1, raise TP1%, tighter trailing
        # Reduced from +0.15 to +0.10 — was taking too much at TP1 in ranging
        p.tp1_atr_mult *= 0.8
        p.tp2_atr_mult *= 0.8
        p.tp1_close_pct = min(1.0, p.tp1_close_pct + 0.10)
        p.trailing_tighten_start = min(0.90, p.trailing_tighten_start + 0.10)
    elif regime == "illiquid":
        # Conservative: tighter everything, close more at TP1
        p.tp1_close_pct = min(1.0, p.tp1_close_pct + 0.20)
        p.sl_atr_mult *= 0.8

    # Volatility adjustments
    if volatility == "high":
        # Wider SL to avoid noise, but also widen targets
        p.sl_atr_mult *= 1.3
        p.tp1_atr_mult *= 1.2
        p.tp2_atr_mult *= 1.2
    elif volatility == "low":
        # Tighter everything, take what the market gives
        p.sl_atr_mult *= 0.8
        p.tp1_atr_mult *= 0.8
        p.tp1_close_pct = min(1.0, p.tp1_close_pct + 0.10)

    return p


def classify_trade(
    signal_metadata: Dict[str, Any],
    confidence: float,
    atr: float,
    entry: float,
    side: str,
) -> TradeProfile:
    """
    Build a TradeProfile from signal metadata.

    This is called BEFORE opening a position. The returned profile
    provides recommended TP1/TP2/SL and exit behavior.

    Args:
        signal_metadata: from ensemble merge (strategies_agree, individual_confidences, etc.)
        confidence: final confidence after ML adjustment
        atr: ATR at entry
        entry: entry price
        side: "BUY" or "SELL"
    """
    strategies_agree = signal_metadata.get("strategies_agree", [])
    individual_confs = signal_metadata.get("individual_confidences", {})
    strategy_weights = signal_metadata.get("strategy_weights", {})

    # 1. Determine primary driver and entry type
    primary = _determine_primary_driver(strategies_agree, individual_confs, strategy_weights)
    entry_type = _determine_entry_type(primary, strategies_agree)

    # 2. Determine regime and volatility
    regime = _determine_regime(signal_metadata)
    vol_band = _determine_volatility_band(atr, entry)

    # 3. Get base exit params for this entry type
    base_params = _BASE_PROFILES.get(entry_type, _BASE_PROFILES[MEDIUM])

    # 4. Adjust for regime and volatility
    params = _adjust_params_for_regime(base_params, regime, vol_band)

    # 5. Compute absolute prices
    if atr > 0:
        if side == "BUY":
            rec_tp1 = entry + atr * params.tp1_atr_mult
            rec_tp2 = entry + atr * params.tp2_atr_mult
            rec_sl = entry - atr * params.sl_atr_mult
        else:
            rec_tp1 = entry - atr * params.tp1_atr_mult
            rec_tp2 = entry - atr * params.tp2_atr_mult
            rec_sl = entry + atr * params.sl_atr_mult
    else:
        rec_tp1 = 0.0
        rec_tp2 = 0.0
        rec_sl = 0.0

    # 6. Build profile
    profile = TradeProfile(
        entry_type=entry_type,
        entry_reasons=strategies_agree,
        primary_driver=primary,
        confidence=confidence,
        regime=regime,
        volatility_band=vol_band,
        timeframe_bias=_timeframe_bias_for_type(entry_type),
        exit_params=params,
        recommended_tp1=rec_tp1,
        recommended_tp2=rec_tp2,
        recommended_sl=rec_sl,
        expected_holding_time=_holding_time_for_type(entry_type),
        notes=f"{entry_type} via {primary} ({STRATEGY_INTENT.get(primary, 'unknown')})",
    )

    logger.info(
        f"Classified: {entry_type} | driver={primary} | regime={regime} "
        f"| vol={vol_band} | TP1%={params.tp1_close_pct:.0%} "
        f"| trailing={params.trailing_style}"
    )

    return profile


# ── Tuning helpers ──────────────────────────────────────────
# These allow adjusting exit parameters per profile without editing _BASE_PROFILES.
# Used by the grid search / parameter sweep system.

def get_profile_config() -> Dict[str, Dict[str, float]]:
    """Return current exit parameters per entry_type as a flat config dict.
    Useful for logging what config is active and for grid search."""
    config = {}
    for etype, params in _BASE_PROFILES.items():
        config[etype] = {
            "tp1_atr_mult": params.tp1_atr_mult,
            "tp2_atr_mult": params.tp2_atr_mult,
            "sl_atr_mult": params.sl_atr_mult,
            "tp1_close_pct": params.tp1_close_pct,
            "trailing_style": params.trailing_style,
        }
    return config


def adjust_profile_params(
    entry_type: str,
    tp1_atr_mult: Optional[float] = None,
    sl_atr_mult: Optional[float] = None,
    tp1_close_pct: Optional[float] = None,
) -> ExitParams:
    """Return a modified copy of the base profile for a given entry_type.

    Used for grid search: try different TP1/SL/TP1% without mutating globals.
    Only the specified parameters are changed; others keep base values.
    """
    base = _BASE_PROFILES.get(entry_type, _BASE_PROFILES[MEDIUM])
    return ExitParams(
        tp1_atr_mult=tp1_atr_mult if tp1_atr_mult is not None else base.tp1_atr_mult,
        tp2_atr_mult=base.tp2_atr_mult,
        sl_atr_mult=sl_atr_mult if sl_atr_mult is not None else base.sl_atr_mult,
        tp1_close_pct=tp1_close_pct if tp1_close_pct is not None else base.tp1_close_pct,
        trailing_style=base.trailing_style,
        trailing_tighten_start=base.trailing_tighten_start,
        trailing_tighten_end=base.trailing_tighten_end,
        floor_progress_start=base.floor_progress_start,
        floor_lock_start=base.floor_lock_start,
        floor_lock_max=base.floor_lock_max,
    )


# Grid search ranges per entry_type (safe, conservative ranges).
# These are hypotheses to be tested, not truths.
TUNING_GRID = {
    SCALP: {
        "tp1_atr_mult": [0.3, 0.4, 0.5, 0.6],
        "sl_atr_mult": [0.3, 0.4, 0.5],
        "tp1_close_pct": [0.80, 0.85, 0.90, 1.0],
    },
    MEDIUM: {
        "tp1_atr_mult": [0.8, 1.0, 1.2],
        "sl_atr_mult": [0.6, 0.75, 0.9],
        "tp1_close_pct": [0.50, 0.60, 0.70],
    },
    TREND: {
        "tp1_atr_mult": [1.0, 1.5, 2.0],
        "sl_atr_mult": [0.8, 1.0, 1.2],
        "tp1_close_pct": [0.25, 0.35, 0.45],
    },
    REGIME: {
        "tp1_atr_mult": [1.0, 1.2, 1.5],
        "sl_atr_mult": [0.7, 0.8, 1.0],
        "tp1_close_pct": [0.40, 0.50, 0.60],
    },
}


def apply_profile_to_signal(
    profile: TradeProfile,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    atr: float,
    side: str,
) -> Dict[str, float]:
    """
    Apply profile-recommended exit levels to a signal.

    Uses the profile's recommended levels when available (ATR > 0),
    otherwise falls back to the signal's original levels.

    Returns dict with adjusted entry, sl, tp1, tp2, tp1_close_pct.
    """
    if atr <= 0 or profile.recommended_tp1 == 0:
        # Can't compute profile-based levels, use originals
        return {
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp1_close_pct": profile.exit_params.tp1_close_pct,
        }

    is_buy = side == "BUY"

    # Use profile-recommended levels
    new_sl = profile.recommended_sl
    new_tp1 = profile.recommended_tp1
    new_tp2 = profile.recommended_tp2

    # Safety: ensure SL is on the correct side of entry
    if is_buy:
        if new_sl >= entry:
            new_sl = sl  # fallback to original
        # TP must be above entry
        if new_tp1 <= entry:
            new_tp1 = tp1
        if new_tp2 <= entry:
            new_tp2 = tp2
    else:
        if new_sl <= entry:
            new_sl = sl
        if new_tp1 >= entry:
            new_tp1 = tp1
        if new_tp2 >= entry:
            new_tp2 = tp2

    return {
        "sl": new_sl,
        "tp1": new_tp1,
        "tp2": new_tp2,
        "tp1_close_pct": profile.exit_params.tp1_close_pct,
    }
