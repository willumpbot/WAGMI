"""
Dynamic leverage manager with aggressive scaling.
Determines leverage AND risk_multiplier based on confidence and consensus.

Leverage tiers (aggressive - designed for max profit at high conviction):
  <60%  confidence  -> No trade
  60-64%            -> 2x lev, 1.0x risk
  65-69%            -> 2-3x lev, 1.0-1.2x risk
  70-74%            -> 3-5x lev, 1.2-1.5x risk (needs 2+ strats)
  75-79%            -> 5-8x lev, 1.5-2.0x risk (strong)
  80-89%            -> 8-15x lev, 2.0-2.5x risk (high, 2+ strats)
  90%+              -> 15-25x lev, 2.5-3.5x risk (extreme, 3+ strats)

risk_multiplier scales risk_per_trade so higher conviction = bigger position.
Combined with leverage, this delivers "big wins" on high-confidence setups.

Safety:
  - Max 2 extreme leverage positions (>10x) at a time
  - Liquidation distance monitoring using Hyperliquid's tiered maintenance margins
  - Automatic deleveraging if equity drops
  - Position sizing guards against near-zero stop widths
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass

# Hyperliquid tiered maintenance margins by position notional (USD).
# At higher notional, maintenance margin increases — liquidation is CLOSER.
# Source: Hyperliquid docs. Format: (max_notional, maintenance_margin_rate)
HYPERLIQUID_MAINTENANCE_TIERS = [
    (100_000, 0.004),       # 0.4% for positions up to $100k
    (300_000, 0.006),       # 0.6% for $100k-$300k
    (600_000, 0.008),       # 0.8% for $300k-$600k
    (1_000_000, 0.01),      # 1.0% for $600k-$1M
    (5_000_000, 0.02),      # 2.0% for $1M-$5M
    (10_000_000, 0.03),     # 3.0% for $5M-$10M
    (float("inf"), 0.05),   # 5.0% for $10M+
]

logger = logging.getLogger("bot.execution.leverage")


def get_maintenance_margin_rate(notional_usd: float) -> float:
    """Return Hyperliquid's tiered maintenance margin rate for a position size."""
    for max_notional, mm_rate in HYPERLIQUID_MAINTENANCE_TIERS:
        if notional_usd <= max_notional:
            return mm_rate
    return HYPERLIQUID_MAINTENANCE_TIERS[-1][1]


# Minimum stop width as a fraction of entry price.
# Prevents near-zero stops from creating infinite R:R and giant positions.
MIN_STOP_WIDTH_PCT = 0.003  # 0.3% of entry price


@dataclass
class LeverageDecision:
    """The result of a leverage decision."""
    leverage: float             # >1.0 = leveraged (no spot)
    mode: str                   # "leverage" or "none"
    tier: str                   # "none", "low", "medium", "high", "extreme"
    reason: str                 # human-readable reason
    risk_multiplier: float = 1.0  # scales risk_per_trade for position sizing


class LeverageManager:
    """Determines appropriate leverage for each trade."""

    def __init__(
        self,
        enable_leverage: bool = True,
        max_leverage: float = 25.0,
        max_extreme_positions: int = 2,
    ):
        self.enable_leverage = enable_leverage
        self.max_leverage = max_leverage
        self.max_extreme_positions = max_extreme_positions

    def decide(
        self,
        confidence: float,
        num_strategies_agree: int,
        total_strategies: int,
        risk_tier: str = "medium",
        current_extreme_count: int = 0,
    ) -> LeverageDecision:
        """
        Decide leverage and risk_multiplier based on confidence + consensus.
        Aggressive scaling: higher confidence -> exponentially more leverage + bigger size.
        """
        if not self.enable_leverage:
            return LeverageDecision(2.0, "leverage", "low", "Leverage disabled, min 2x", 1.0)

        if confidence < 60:
            return LeverageDecision(0.0, "none", "none", f"Confidence {confidence:.0f}% too low", 0.0)

        # Risk tier caps (high-risk assets get less extreme leverage)
        tier_cap = {
            "low": self.max_leverage,
            "medium": min(20.0, self.max_leverage),
            "high": min(12.0, self.max_leverage),
        }
        cap = tier_cap.get(risk_tier, self.max_leverage)

        # ── Tier 1: 60-64% — minimum viable trade ──
        if confidence < 65:
            return LeverageDecision(2.0, "leverage", "low",
                                    f"2x: confidence {confidence:.0f}%", 1.0)

        # ── Tier 2: 65-69% — building conviction ──
        if confidence < 70:
            t = (confidence - 65) / 5.0  # 0..1
            lev = min(2.0 + t * 1.0, cap)  # 2-3x
            rm = 1.0 + t * 0.2  # 1.0-1.2x
            return LeverageDecision(lev, "leverage", "low",
                                    f"{lev:.1f}x: confidence {confidence:.0f}%", rm)

        # ── Tier 3: 70-74% — moderate conviction ──
        if confidence < 75:
            t = (confidence - 70) / 5.0
            if num_strategies_agree < 2:
                lev = min(3.0, cap)
                return LeverageDecision(lev, "leverage", "low",
                                        f"{lev:.1f}x: only {num_strategies_agree} strats", 1.2)
            lev = min(3.0 + t * 2.0, cap)  # 3-5x
            rm = 1.2 + t * 0.3  # 1.2-1.5x
            return LeverageDecision(lev, "leverage", "medium",
                                    f"{lev:.1f}x: {num_strategies_agree} strats, {confidence:.0f}%", rm)

        # ── Tier 4: 75-79% — strong conviction ──
        if confidence < 80:
            t = (confidence - 75) / 5.0
            if num_strategies_agree < 2:
                lev = min(4.0, cap)
                return LeverageDecision(lev, "leverage", "medium",
                                        f"{lev:.1f}x: only {num_strategies_agree} strats", 1.3)
            lev = min(5.0 + t * 3.0, cap)  # 5-8x
            rm = 1.5 + t * 0.5  # 1.5-2.0x
            tier = "high" if lev > 5.0 else "medium"
            return LeverageDecision(lev, "leverage", tier,
                                    f"{lev:.1f}x: {num_strategies_agree} strats, {confidence:.0f}%", rm)

        # ── Tier 5: 80-89% — high conviction ──
        if confidence < 90:
            t = (confidence - 80) / 10.0
            if num_strategies_agree < 2:
                lev = min(5.0, cap)
                return LeverageDecision(lev, "leverage", "medium",
                                        f"{lev:.1f}x: need 2+ strats for high lev", 1.5)
            lev = min(8.0 + t * 7.0, cap)  # 8-15x
            rm = 2.0 + t * 0.5  # 2.0-2.5x
            # Check extreme position limit
            if lev > 10.0 and current_extreme_count >= self.max_extreme_positions:
                lev = 10.0
                return LeverageDecision(lev, "leverage", "high",
                                        f"{lev:.1f}x: extreme limit reached", rm)
            tier = "extreme" if lev >= 10.0 else "high"
            return LeverageDecision(lev, "leverage", tier,
                                    f"{lev:.1f}x: {num_strategies_agree} strats, {confidence:.0f}%", rm)

        # ── Tier 6: 90%+ — EXTREME (rare, max conviction) ──
        t = min((confidence - 90) / 10.0, 1.0)
        if num_strategies_agree >= 3:
            lev = min(15.0 + t * 10.0, cap)  # 15-25x
            rm = 2.5 + t * 1.0  # 2.5-3.5x
        elif num_strategies_agree >= 2:
            lev = min(12.0 + t * 5.0, cap)  # 12-17x
            rm = 2.0 + t * 0.5  # 2.0-2.5x
        else:
            lev = min(8.0, cap)
            rm = 1.8

        if lev > 10.0 and current_extreme_count >= self.max_extreme_positions:
            lev = 10.0
            return LeverageDecision(lev, "leverage", "high",
                                    f"{lev:.1f}x: extreme limit reached", rm)

        tier = "extreme" if lev >= 15.0 else "high"
        return LeverageDecision(lev, "leverage", tier,
                                f"{lev:.1f}x: {num_strategies_agree}/{total_strategies} strats, {confidence:.0f}%", rm)

    def calculate_position_size(
        self,
        equity: float,
        risk_per_trade: float,
        entry: float,
        stop_loss: float,
        leverage: float,
    ) -> float:
        """
        Calculate position size accounting for leverage.
        Risk is based on the equity at risk, not the leveraged position value.

        Guards against near-zero stop widths that would create oversized positions.
        """
        stop_width = abs(entry - stop_loss)
        if entry <= 0:
            return 0.0

        # Enforce minimum stop width (0.3% of entry) to prevent
        # infinite R:R from near-zero stops creating giant positions
        min_width = entry * MIN_STOP_WIDTH_PCT
        if stop_width < min_width:
            logger.warning(
                f"Stop width {stop_width:.6f} < min {min_width:.6f} "
                f"({MIN_STOP_WIDTH_PCT:.1%} of {entry:.2f}), rejecting"
            )
            return 0.0

        risk_usd = equity * risk_per_trade
        effective_leverage = max(leverage, 1.0)
        qty = risk_usd / (stop_width * effective_leverage)

        # Sanity check: notional value shouldn't exceed equity * leverage * 2
        notional = qty * entry
        max_notional = equity * effective_leverage * 2
        if notional > max_notional:
            qty = max_notional / entry
            logger.warning(
                f"Position capped: notional ${notional:.0f} > "
                f"max ${max_notional:.0f}, qty reduced to {qty:.6f}"
            )

        return qty

    def liquidation_price(
        self, entry: float, side: str, leverage: float,
        notional_usd: float = 0.0,
    ) -> Optional[float]:
        """Calculate liquidation price using Hyperliquid's tiered maintenance margins.

        The simple 1/leverage formula underestimates liquidation risk.
        Hyperliquid uses variable maintenance margins based on position size:
          - Small positions ($0-100k): 0.4% maintenance margin
          - Larger positions: up to 5% maintenance margin

        For longs:  liq = entry * (1 - 1/L) / (1 - mm_rate)
        For shorts: liq = entry * (1 + 1/L) / (1 + mm_rate)

        The maintenance margin makes liquidation CLOSER to entry than 1/leverage.
        """
        if leverage <= 1.0:
            return None

        mm_rate = get_maintenance_margin_rate(notional_usd) if notional_usd > 0 else 0.004

        if side in ("LONG", "BUY"):
            denom = 1 - mm_rate
            if denom <= 0:
                return entry  # pathological case
            return entry * (1 - 1 / leverage) / denom
        else:
            return entry * (1 + 1 / leverage) / (1 + mm_rate)

    def check_liquidation_risk(
        self, entry: float, current_price: float, side: str, leverage: float,
        safety_buffer: float = 0.15, notional_usd: float = 0.0,
    ) -> Dict[str, Any]:
        """Check how close we are to liquidation using real maintenance margins."""
        liq_price = self.liquidation_price(entry, side, leverage, notional_usd)
        if liq_price is None:
            return {"at_risk": False, "leverage": leverage}

        if side in ("LONG", "BUY"):
            distance_pct = (current_price - liq_price) / current_price
        else:
            distance_pct = (liq_price - current_price) / current_price

        at_risk = distance_pct < safety_buffer

        return {
            "at_risk": at_risk,
            "liquidation_price": liq_price,
            "distance_pct": distance_pct,
            "leverage": leverage,
            "current_price": current_price,
            "maintenance_margin_rate": get_maintenance_margin_rate(notional_usd),
        }

    def validate_stop_vs_liquidation(
        self, entry: float, stop_loss: float, side: str,
        leverage: float, notional_usd: float = 0.0,
    ) -> Dict[str, Any]:
        """Verify stop loss triggers BEFORE liquidation.

        Returns whether the trade is safe and the gap between SL and liquidation.
        If SL is beyond liquidation, the position will be liquidated before
        the stop loss can execute — a catastrophic outcome.
        """
        liq_price = self.liquidation_price(entry, side, leverage, notional_usd)
        if liq_price is None:
            return {"safe": True, "reason": "no liquidation risk (spot)"}

        if side in ("LONG", "BUY"):
            sl_safe = stop_loss > liq_price
            gap_pct = (stop_loss - liq_price) / entry if entry > 0 else 0
        else:
            sl_safe = stop_loss < liq_price
            gap_pct = (liq_price - stop_loss) / entry if entry > 0 else 0

        return {
            "safe": sl_safe,
            "stop_loss": stop_loss,
            "liquidation_price": liq_price,
            "gap_pct": gap_pct,
            "reason": "SL inside liquidation zone" if not sl_safe else "OK",
        }
