"""
Dynamic TP/SL Optimization using MFE (Maximum Favorable Excursion) data.

Uses per-symbol MFE-optimal TP1/SL as baseline, then adjusts based on:
- Market regime (trending/ranging)
- Volume (high volume = momentum carries further)
- Time of day (dead hours = less follow-through)
- ATR percentile (high ATR = wider moves)

This is an enhancement layer — it does NOT replace existing TP/SL logic.
It adjusts the final TP1/SL values after the trade profile system has
computed its ATR-based levels.

Enable/disable via DYNAMIC_TP_ENABLED env var (default: True).
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("bot.execution.dynamic_tp")


# ─── Per-symbol MFE-optimal TP1/SL (percentage of entry price) ────────
# Derived from 2h holding-window MFE/MAE analysis on Hyperliquid.
# These are the *optimal* TP1 and SL widths as percentages.

MFE_OPTIMAL_LEVELS: Dict[str, Dict[str, float]] = {
    "BTC": {"tp1_pct": 0.38, "sl_pct": 0.72},
    "SOL": {"tp1_pct": 0.51, "sl_pct": 0.96},
    "ETH": {"tp1_pct": 0.44, "sl_pct": 0.90},
    "HYPE": {"tp1_pct": 0.78, "sl_pct": 1.34},
}

# Fallback for unlisted symbols — conservative average
DEFAULT_MFE_LEVELS = {"tp1_pct": 0.45, "sl_pct": 0.85}


# ─── Adjustment multipliers ──────────────────────────────────────────

# Regime adjustments
REGIME_TP_ADJUSTMENTS: Dict[str, float] = {
    "trending": 1.25,       # Trending: widen TP by 25% (momentum carries)
    "trending_bull": 1.25,
    "trending_bear": 1.25,
    "trend": 1.25,
    "ranging": 0.80,        # Ranging: tighten TP by 20% (mean-reversion)
    "range": 0.80,
    "consolidation": 0.80,
    "illiquid": 0.85,       # Illiquid: slightly tighter
    "high_volatility": 1.10,
    "panic": 0.75,          # Panic: grab what you can
    "unknown": 1.0,
}

# Volume threshold for "high volume" classification
HIGH_VOLUME_RATIO = 1.5  # current volume > 1.5x average = high volume
HIGH_VOLUME_TP_MULT = 1.20  # Widen TP by 20% on high volume

# Dead hours (UTC): 03:00-06:00 — lower liquidity, less follow-through
DEAD_HOUR_START = 3
DEAD_HOUR_END = 6
DEAD_HOUR_TP_MULT = 0.85  # Tighten TP by 15% during dead hours

# ATR percentile adjustment
# If current ATR > 75th percentile of recent ATR, widen TP
HIGH_ATR_TP_MULT = 1.15  # Widen TP by 15% on high ATR


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _normalise_symbol(symbol: str) -> str:
    """Strip exchange suffixes: 'BTC/USDT:USDT' -> 'BTC'."""
    sym = symbol.upper()
    for suffix in ("/USDT:USDT", "/USDC:USDC", "/USDT", "-PERP", "-USD", "USDT", "USD"):
        if sym.endswith(suffix):
            sym = sym[: -len(suffix)]
            break
    return sym


@dataclass
class DynamicTPResult:
    """Result of dynamic TP/SL optimization."""
    tp1: float              # Adjusted TP1 price
    sl: float               # Adjusted SL price
    tp1_pct_from_entry: float  # TP1 distance as % of entry
    sl_pct_from_entry: float   # SL distance as % of entry
    adjustments: list       # List of adjustments applied
    mfe_baseline_tp1_pct: float  # Original MFE baseline TP1%
    mfe_baseline_sl_pct: float   # Original MFE baseline SL%
    enabled: bool = True


class DynamicTPOptimizer:
    """
    Adjusts TP1/SL based on per-symbol MFE data and market conditions.

    This is an enhancement layer that sits between the trade profile
    system and the final position opening. It takes the profile-computed
    TP1/SL and blends them with MFE-optimal levels.

    Parameters
    ----------
    blend_weight : float
        How much to weight MFE-optimal vs profile-computed levels.
        0.0 = use only profile levels, 1.0 = use only MFE levels.
        Default 0.6 (lean toward MFE data).
    """

    def __init__(self, blend_weight: float = None):
        self.enabled = _env_bool("DYNAMIC_TP_ENABLED", True)
        self.blend_weight = blend_weight if blend_weight is not None else _env_float("DYNAMIC_TP_BLEND_WEIGHT", 0.6)

    def optimize(
        self,
        symbol: str,
        side: str,
        entry: float,
        current_tp1: float,
        current_sl: float,
        regime: str = "unknown",
        volume_ratio: float = 1.0,
        atr: float = 0.0,
        atr_p75: float = 0.0,
        utc_hour: Optional[int] = None,
    ) -> DynamicTPResult:
        """
        Compute MFE-optimized TP1 and SL for a trade.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "BTC", "SOL/USDT:USDT").
        side : str
            "BUY" or "SELL".
        entry : float
            Entry price.
        current_tp1 : float
            Profile-computed TP1 price.
        current_sl : float
            Profile-computed SL price.
        regime : str
            Current market regime.
        volume_ratio : float
            Current volume / average volume ratio.
        atr : float
            Current ATR value.
        atr_p75 : float
            75th percentile ATR (for high-ATR detection). 0 = skip ATR adjustment.
        utc_hour : int, optional
            Current UTC hour. None = use system clock.

        Returns
        -------
        DynamicTPResult
            Optimized TP1/SL with adjustment log.
        """
        if not self.enabled or entry <= 0:
            return DynamicTPResult(
                tp1=current_tp1,
                sl=current_sl,
                tp1_pct_from_entry=0.0,
                sl_pct_from_entry=0.0,
                adjustments=["disabled"],
                mfe_baseline_tp1_pct=0.0,
                mfe_baseline_sl_pct=0.0,
                enabled=False,
            )

        # Pure profile passthrough when blend=0
        if self.blend_weight <= 0.0:
            tp1_pct = abs(current_tp1 - entry) / entry * 100 if entry > 0 else 0
            sl_pct = abs(current_sl - entry) / entry * 100 if entry > 0 else 0
            sym = _normalise_symbol(symbol)
            mfe = MFE_OPTIMAL_LEVELS.get(sym, DEFAULT_MFE_LEVELS)
            return DynamicTPResult(
                tp1=current_tp1,
                sl=current_sl,
                tp1_pct_from_entry=tp1_pct,
                sl_pct_from_entry=sl_pct,
                adjustments=["blend=0: using profile levels only"],
                mfe_baseline_tp1_pct=mfe["tp1_pct"],
                mfe_baseline_sl_pct=mfe["sl_pct"],
                enabled=True,
            )

        sym = _normalise_symbol(symbol)
        mfe = MFE_OPTIMAL_LEVELS.get(sym, DEFAULT_MFE_LEVELS)
        adjustments = []

        # ── Step 1: Get MFE baseline TP1/SL as percentages ──
        base_tp1_pct = mfe["tp1_pct"]
        base_sl_pct = mfe["sl_pct"]
        adjustments.append(f"MFE baseline: TP1={base_tp1_pct:.2f}%, SL={base_sl_pct:.2f}%")

        # ── Step 2: Apply dynamic adjustments to the MFE baseline ──
        tp1_mult = 1.0
        sl_mult = 1.0

        # 2a. Regime adjustment
        regime_adj = REGIME_TP_ADJUSTMENTS.get(regime, 1.0)
        if regime_adj != 1.0:
            tp1_mult *= regime_adj
            # SL follows regime too but less aggressively
            if regime_adj > 1.0:
                sl_mult *= 1.0 + (regime_adj - 1.0) * 0.5  # half the TP widening
            else:
                sl_mult *= 1.0 + (regime_adj - 1.0) * 0.3  # less SL tightening
            adjustments.append(f"regime={regime}: TP×{regime_adj:.2f}, SL×{sl_mult:.2f}")

        # 2b. Volume adjustment
        if volume_ratio >= HIGH_VOLUME_RATIO:
            tp1_mult *= HIGH_VOLUME_TP_MULT
            adjustments.append(f"high_volume ({volume_ratio:.1f}x): TP×{HIGH_VOLUME_TP_MULT}")

        # 2c. Time-of-day adjustment
        if utc_hour is None:
            utc_hour = datetime.now(timezone.utc).hour
        if DEAD_HOUR_START <= utc_hour < DEAD_HOUR_END:
            tp1_mult *= DEAD_HOUR_TP_MULT
            adjustments.append(f"dead_hours (UTC {utc_hour}h): TP×{DEAD_HOUR_TP_MULT}")

        # 2d. ATR percentile adjustment
        if atr > 0 and atr_p75 > 0 and atr > atr_p75:
            tp1_mult *= HIGH_ATR_TP_MULT
            sl_mult *= HIGH_ATR_TP_MULT  # widen SL too when ATR is high
            adjustments.append(f"high_ATR ({atr:.4f} > p75 {atr_p75:.4f}): TP×{HIGH_ATR_TP_MULT}")

        # ── Step 3: Compute adjusted MFE-optimal TP1/SL percentages ──
        adj_tp1_pct = base_tp1_pct * tp1_mult
        adj_sl_pct = base_sl_pct * sl_mult

        # ── Step 4: Convert percentages to absolute prices ──
        is_buy = side.upper() in ("BUY", "LONG")
        if is_buy:
            mfe_tp1_price = entry * (1 + adj_tp1_pct / 100)
            mfe_sl_price = entry * (1 - adj_sl_pct / 100)
        else:
            mfe_tp1_price = entry * (1 - adj_tp1_pct / 100)
            mfe_sl_price = entry * (1 + adj_sl_pct / 100)

        # ── Step 5: Blend MFE-optimal with profile-computed levels ──
        # Use blend_weight to mix: higher weight = more MFE influence
        w = self.blend_weight
        final_tp1 = mfe_tp1_price * w + current_tp1 * (1 - w)
        final_sl = mfe_sl_price * w + current_sl * (1 - w)

        # ── Step 6: Safety checks ──
        # Ensure TP1 is on the correct side of entry
        if is_buy:
            if final_tp1 <= entry:
                final_tp1 = current_tp1  # fallback to profile
                adjustments.append("SAFETY: TP1 below entry, using profile TP1")
            if final_sl >= entry:
                final_sl = current_sl  # fallback to profile
                adjustments.append("SAFETY: SL above entry, using profile SL")
        else:
            if final_tp1 >= entry:
                final_tp1 = current_tp1
                adjustments.append("SAFETY: TP1 above entry (short), using profile TP1")
            if final_sl <= entry:
                final_sl = current_sl
                adjustments.append("SAFETY: SL below entry (short), using profile SL")

        # Ensure minimum R:R of 0.3 (MFE data intentionally has TP < SL
        # for high-WR scalping — 1.0 floor would override all adjustments)
        MIN_RR = 0.3
        tp1_dist = abs(final_tp1 - entry)
        sl_dist = abs(final_sl - entry)
        if sl_dist > 0 and tp1_dist / sl_dist < MIN_RR:
            # Widen TP1 to maintain minimum R:R
            if is_buy:
                final_tp1 = entry + sl_dist * MIN_RR
            else:
                final_tp1 = entry - sl_dist * MIN_RR
            adjustments.append(f"R:R floor: widened TP1 to maintain {MIN_RR} R:R")

        # Compute final percentages for logging
        final_tp1_pct = abs(final_tp1 - entry) / entry * 100 if entry > 0 else 0
        final_sl_pct = abs(final_sl - entry) / entry * 100 if entry > 0 else 0

        adjustments.append(f"final: TP1={final_tp1_pct:.3f}%, SL={final_sl_pct:.3f}%")

        logger.info(
            f"[DynamicTP] {sym} {side}: MFE TP1={base_tp1_pct:.2f}% -> {final_tp1_pct:.3f}%, "
            f"SL={base_sl_pct:.2f}% -> {final_sl_pct:.3f}% "
            f"(blend={w:.1f}, regime={regime}, vol_ratio={volume_ratio:.1f})"
        )

        return DynamicTPResult(
            tp1=round(final_tp1, 8),
            sl=round(final_sl, 8),
            tp1_pct_from_entry=final_tp1_pct,
            sl_pct_from_entry=final_sl_pct,
            adjustments=adjustments,
            mfe_baseline_tp1_pct=base_tp1_pct,
            mfe_baseline_sl_pct=base_sl_pct,
            enabled=True,
        )


# ─── Module-level singleton ──────────────────────────────────────────

_optimizer = DynamicTPOptimizer()


def optimize_tp_sl(
    symbol: str,
    side: str,
    entry: float,
    current_tp1: float,
    current_sl: float,
    regime: str = "unknown",
    volume_ratio: float = 1.0,
    atr: float = 0.0,
    atr_p75: float = 0.0,
    utc_hour: Optional[int] = None,
) -> DynamicTPResult:
    """Module-level convenience: optimize TP1/SL with MFE data."""
    return _optimizer.optimize(
        symbol=symbol,
        side=side,
        entry=entry,
        current_tp1=current_tp1,
        current_sl=current_sl,
        regime=regime,
        volume_ratio=volume_ratio,
        atr=atr,
        atr_p75=atr_p75,
        utc_hour=utc_hour,
    )
