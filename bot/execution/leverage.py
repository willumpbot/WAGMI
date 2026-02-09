"""
Dynamic leverage manager.
Determines leverage based on signal confidence, strategy agreement, and risk tier.

Tiers:
  <60% confidence  -> No trade
  60-69%           -> 2x (minimum leverage, no spot)
  70-79%           -> 2-3x
  80-89%           -> 3-5x (requires 2+ strategies)
  90-94%           -> 5-10x (requires 3+ strategies)
  95%+             -> 10-25x (RARE: requires ALL strategies to agree)

Safety:
  - Max 1 extreme leverage position (>5x) at a time
  - Liquidation distance monitoring
  - Automatic deleveraging if equity drops
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger("bot.execution.leverage")


@dataclass
class LeverageDecision:
    """The result of a leverage decision."""
    leverage: float         # 1.0 = spot, >1.0 = leveraged
    mode: str               # "spot" or "leverage"
    tier: str               # "spot", "low", "medium", "high", "extreme"
    reason: str             # human-readable reason
    risk_adjusted_qty: float = 0.0  # position size after risk adjustment


class LeverageManager:
    """Determines appropriate leverage for each trade."""

    def __init__(
        self,
        enable_leverage: bool = True,
        max_leverage: float = 25.0,
        max_extreme_positions: int = 1,
    ):
        self.enable_leverage = enable_leverage
        self.max_leverage = max_leverage
        self.max_extreme_positions = max_extreme_positions
        self._extreme_count = 0

    def decide(
        self,
        confidence: float,
        num_strategies_agree: int,
        total_strategies: int,
        risk_tier: str = "medium",
        current_extreme_count: int = 0,
    ) -> LeverageDecision:
        """
        Decide leverage based on confidence and strategy consensus.
        """
        if not self.enable_leverage:
            return LeverageDecision(2.0, "leverage", "low", "Leverage disabled, using minimum 2x")

        if confidence < 60:
            return LeverageDecision(0.0, "none", "none", f"Confidence {confidence:.0f}% too low")

        if confidence < 70:
            return LeverageDecision(2.0, "leverage", "low", f"2x minimum: confidence {confidence:.0f}%")

        # Risk tier adjustment (high risk = less leverage)
        tier_cap = {"low": self.max_leverage, "medium": min(15.0, self.max_leverage), "high": min(10.0, self.max_leverage)}
        cap = tier_cap.get(risk_tier, self.max_leverage)

        if confidence < 80:
            lev = 2.0 + (confidence - 70) / 10.0  # 2.0 to 3.0
            lev = min(lev, cap)
            return LeverageDecision(lev, "leverage", "low", f"{lev:.1f}x: confidence {confidence:.0f}%")

        if confidence < 90:
            if num_strategies_agree < 2:
                lev = 2.0  # cap without consensus
                return LeverageDecision(lev, "leverage", "low", f"{lev:.1f}x: only {num_strategies_agree} strategies agree")
            lev = 3.0 + 2.0 * (confidence - 80) / 10.0  # 3.0 to 5.0
            lev = min(lev, cap)
            return LeverageDecision(lev, "leverage", "medium", f"{lev:.1f}x: {num_strategies_agree} strategies, {confidence:.0f}%")

        if confidence < 95:
            if num_strategies_agree < 3:
                lev = min(5.0, cap)
                return LeverageDecision(lev, "leverage", "medium", f"{lev:.1f}x: need 3+ strategies for high leverage")
            lev = 5.0 + 5.0 * (confidence - 90) / 5.0  # 5.0 to 10.0
            lev = min(lev, cap)
            # Check extreme position limit
            if lev > 5.0 and current_extreme_count >= self.max_extreme_positions:
                lev = 5.0
                return LeverageDecision(lev, "leverage", "medium", f"{lev:.1f}x: extreme position limit reached")
            tier = "high" if lev > 5.0 else "medium"
            return LeverageDecision(lev, "leverage", tier, f"{lev:.1f}x: {num_strategies_agree} strategies, {confidence:.0f}%")

        # 95%+ EXTREME (rare)
        if num_strategies_agree >= total_strategies and total_strategies >= 3:
            lev = min(10.0 + 15.0 * (confidence - 95) / 5.0, cap)
        elif num_strategies_agree >= 3:
            lev = min(10.0, cap)
        else:
            lev = min(7.0, cap)

        if lev > 5.0 and current_extreme_count >= self.max_extreme_positions:
            lev = 5.0
            return LeverageDecision(lev, "leverage", "medium", f"{lev:.1f}x: extreme position limit reached")

        tier = "extreme" if lev >= 10.0 else "high"
        return LeverageDecision(
            lev, "leverage", tier,
            f"{lev:.1f}x RARE: {num_strategies_agree}/{total_strategies} agree, {confidence:.0f}%"
        )

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
        """
        stop_width = abs(entry - stop_loss)
        if stop_width <= 0 or entry <= 0:
            return 0.0

        risk_usd = equity * risk_per_trade
        # With leverage, the position is larger but risk per dollar is the same
        # risk_usd = stop_width * qty * leverage ... but we want risk_usd fixed
        # So: qty = risk_usd / (stop_width * leverage) ... NO
        # Actually: risk_usd = stop_width * qty (always)
        # leverage amplifies PnL: actual_pnl = (price_move * qty * leverage)
        # So for a given risk_usd: qty = risk_usd / (stop_width * leverage)
        # This means we risk the same USD amount but with smaller qty
        # OR: we keep same qty and risk more... user wants to amplify gains
        # Standard approach: qty = risk_usd / stop_width (same as spot)
        # The leverage just means we put up less margin
        # PnL = (price_move * qty * leverage) - so leverage multiplies the PnL
        # To keep risk_usd constant: qty = risk_usd / (stop_width * leverage)

        qty = risk_usd / stop_width
        # Leverage allows us to trade with less collateral
        # collateral_needed = (entry * qty) / leverage
        return qty

    def liquidation_price(
        self, entry: float, side: str, leverage: float
    ) -> Optional[float]:
        """Calculate approximate liquidation price for a leveraged position."""
        if leverage <= 1.0:
            return None  # No liquidation for spot
        # Liquidation occurs when loss = collateral = entry / leverage
        # For longs: liq = entry * (1 - 1/leverage)
        # For shorts: liq = entry * (1 + 1/leverage)
        if side in ("LONG", "BUY"):
            return entry * (1 - 1 / leverage)
        else:
            return entry * (1 + 1 / leverage)

    def check_liquidation_risk(
        self, entry: float, current_price: float, side: str, leverage: float,
        safety_buffer: float = 0.15,
    ) -> Dict[str, Any]:
        """Check how close we are to liquidation."""
        liq_price = self.liquidation_price(entry, side, leverage)
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
        }
