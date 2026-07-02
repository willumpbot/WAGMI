"""
Dynamic leverage manager with CONSERVATIVE scaling.
Determines leverage AND risk_multiplier based on confidence and consensus.

Leverage tiers (survival-first — Full Kelly=7.8x, Half-Kelly=3.9x from edge study):
  <20%  confidence  -> No trade
  20-64%            -> 2.0x lev, 0.3x risk (minimum viable)
  65-69%            -> 2.0x lev, 0.5x risk
  70-74%            -> ~2x lev, 0.75x risk (quarter Kelly)
  75-79%            -> 2.6-3.9x lev, 1.0x risk (third Kelly)
  80-84%            -> 3.9-5.2x lev, 1.1x risk (half Kelly, optimal growth)
  85-89%            -> 5.2-5.9x lev, 1.2x risk (2/3 Kelly)
  90%+              -> ~5.9x lev, 1.3x risk (3/4 Kelly)

Philosophy: survive first, scale later. High leverage with low win rate
is guaranteed ruin. Keep leverage low, let edge compound.

Safety:
  - Max 2 extreme leverage positions (>5x) at a time
  - Liquidation distance monitoring using Hyperliquid's tiered maintenance margins
  - Automatic deleveraging if equity drops
  - Position sizing guards against near-zero stop widths
"""

import logging
import os
from typing import Dict, Optional, Any
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    """Read a float from environment, fall back to default."""
    val = os.environ.get(name)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool from environment, fall back to default."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

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
# Single source of truth: trading_config.py MIN_STOP_WIDTH_PCT env var (default 0.002).
from trading_config import TradingConfig as _TC
MIN_STOP_WIDTH_PCT = _TC().min_stop_width_pct


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
        max_risk_multiplier: float = 1.5,
    ):
        self.enable_leverage = enable_leverage
        self.max_leverage = max_leverage
        self.max_extreme_positions = max_extreme_positions
        self.max_risk_multiplier = max_risk_multiplier

    def decide(
        self,
        confidence: float,
        num_strategies_agree: int,
        total_strategies: int,
        risk_tier: str = "medium",
        current_extreme_count: int = 0,
        recent_win_rate: float = -1.0,
        baseline_win_rate: float = 0.45,
        symbol: str = "",
    ) -> LeverageDecision:
        """
        Decide leverage and risk_multiplier based on confidence + consensus.
        Aggressive scaling: higher confidence -> exponentially more leverage + bigger size.

        Win-rate scaling: if recent_win_rate is provided (>= 0), scale leverage
        down when the bot is underperforming its baseline. This prevents the bot
        from sizing up during losing streaks.
        """
        if not self.enable_leverage:
            return LeverageDecision(2.0, "leverage", "low", "Leverage disabled, min 2x", 1.0)

        if confidence < 20:
            return LeverageDecision(0.0, "none", "none", f"Confidence {confidence:.0f}% too low", 0.0)

        # ── SCALP-KELLY LEVERAGE ──────────────────────────────────
        # Best trade: BTC SHORT 10x, held 36 min, +$38. High lev + fast exit.
        # Wick noise at 5min resolution: BTC 0.15%, SOL 0.21%, HYPE 0.31%
        # At 15x with 5-10min holds, 0.15% wick = 2.25% DD — survivable.
        # The problem was HOLD TIME not leverage. Fix exits, not leverage.
        #
        # Kelly-optimal per symbol (factoring 5min noise + WR):
        _SCALP_KELLY_LEV = {
            "BTC": 7.0,    # Capped: data shows 5-7x optimal, 7-9x loses
            "ETH": 7.0,    # Capped at 7x
            "SOL": 7.0,    # Already at 7x
            "HYPE": 5.0,   # Already at 5x
        }
        _sym_clean = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").split("/")[0]
        FULL_KELLY_LEV = _SCALP_KELLY_LEV.get(_sym_clean, 7.0)
        # DE-HARDCODE (2026-06-23): removed the +20% boost for 3-agree (was 1.20). It rewarded RAW
        # vote count, which correlated oscillators inflate — the code's own comment says "4+ agree =
        # 0% WR, redundant oscillators fire together" — and there is NO evidence raw agreement helps
        # (the "high agreement = worse" finding was an exit-agent confound). Boost capped at 1.0 so
        # agreement can no longer INCREASE leverage. The low-agreement caution (0.80x) is kept as a
        # risk control. Re-derive from n_independent + measured edge before letting agreement boost.
        _agree_mult = {1: 0.80, 2: 1.0, 3: 1.0}.get(
            min(num_strategies_agree, 3), 1.0
        )

        # Leverage caps for scalp-Kelly approach
        tier_cap = {
            "low": min(15.0, self.max_leverage),    # BTC/ETH: up to 15x for scalps
            "medium": min(10.0, self.max_leverage),  # SOL: up to 10x
            "high": min(8.0, self.max_leverage),     # HYPE: up to 8x
        }
        cap = tier_cap.get(risk_tier, self.max_leverage)

        # Helper to apply WR scaling to all return paths
        def _wr(d: LeverageDecision) -> LeverageDecision:
            return self._apply_wr_scaling(d, recent_win_rate, baseline_win_rate)

        # ── KELLY-SCALED LEVERAGE ──────────────────────────────────────
        # Scale: confidence x agreement -> Kelly fraction -> leverage
        # Low confidence = low leverage. Size also scales via risk_multiplier.
        # Previous bug: FULL_KELLY_LEV=19.5 produced 12-14x for all trades,
        # causing instant CB trips (15% DD from a single 1.25% adverse move
        # at 12x). Now aligned with actual edge study values.

        # ── FULL KELLY — NO SANDBAGGING ──────────────────────────────
        # User wants FULL Kelly. Not quarter, not half, not two-thirds.
        # Full Kelly = 7.8x. Confidence scales risk_multiplier (size),
        # NOT leverage. Every trade gets Kelly leverage. Low confidence
        # = smaller size, same leverage. This is how Kelly actually works.

        # Base leverage: Full Kelly for all trades
        base_lev = FULL_KELLY_LEV  # 7.8x

        # Confidence only scales SIZE (risk_multiplier), not leverage
        #
        # SHIP S3 (2026-07-02): V2 cut-only confidence sizing ladder.
        # BT_SIZING_LADDER (n=90 replay): conf 60-69 = 17.4% WR (-$374, n=46);
        # 70-79 = 0-for-14 (-$722). Cutting 60-79 to 0.15x turns the
        # known-confidence book from -$1,008 to -$67 and cuts max DD ~85%.
        # NO upweight above 80: GOLDMINE confirmed confidence is
        # anti-predictive above 70 (era-split AUC 0.43-0.51), and the 80+
        # band is n=8 / one regime — below the n>=13 evidence bar. The old
        # 1.3x/1.5x boosts are therefore held at 1.0x (cut-only ladder).
        # Flag-revertible: CONF_LADDER_ENABLED=false restores the previous
        # 0.6/0.8/1.0/1.3/1.5 ladder; per-band env overrides below.
        if _env_bool("CONF_LADDER_ENABLED", True):
            if confidence < 60:
                rm = _env_float("CONF_LADDER_MULT_LT60", 0.15)
            elif confidence < 70:
                rm = _env_float("CONF_LADDER_MULT_60_69", 0.15)
            elif confidence < 80:
                rm = _env_float("CONF_LADDER_MULT_70_79", 0.15)
            elif confidence < 90:
                rm = _env_float("CONF_LADDER_MULT_80_89", 1.0)
            else:
                rm = _env_float("CONF_LADDER_MULT_90P", 1.0)
        else:
            # Pre-S3 ladder (kept as the CONF_LADDER_ENABLED=false revert path)
            if confidence < 60:
                rm = 0.6
            elif confidence < 70:
                rm = 0.8
            elif confidence < 80:
                rm = 1.0
            elif confidence < 90:
                rm = 1.3
            else:
                rm = 1.5  # Max conviction

        # Agreement scales leverage (more strategies agree = more leverage)
        lev = min(base_lev * _agree_mult, cap)

        # Tier label for logging
        if confidence >= 85:
            tier = "high"
        elif confidence >= 70:
            tier = "medium"
        else:
            tier = "low"

        if lev > 6.0 and current_extreme_count >= self.max_extreme_positions:
            lev = 6.0  # Still meaningful, not crushed to 4x
            return _wr(LeverageDecision(lev, "leverage", tier,
                                        f"{lev:.1f}x: extreme limit capped, {confidence:.0f}%", rm))

        return self._apply_wr_scaling(
            LeverageDecision(lev, "leverage", tier,
                             f"{lev:.1f}x: full-Kelly, {num_strategies_agree} strats, {confidence:.0f}%, rm={rm:.1f}", rm),
            recent_win_rate, baseline_win_rate,
        )

    def _apply_wr_scaling(
        self, decision: LeverageDecision,
        recent_win_rate: float, baseline_win_rate: float,
    ) -> LeverageDecision:
        """Scale leverage and risk_multiplier by rolling win rate vs baseline.

        When the bot is underperforming (recent WR < baseline), reduce exposure.
        When at or above baseline, no change. This prevents compounding losses
        during losing streaks while preserving full sizing during winning streaks.
        """
        if recent_win_rate < 0 or baseline_win_rate <= 0:
            return decision  # No WR data available, skip scaling
        if decision.leverage <= 0:
            return decision  # No trade, nothing to scale

        wr_scale = max(0.5, min(1.0, recent_win_rate / baseline_win_rate))
        if wr_scale < 1.0:
            old_lev = decision.leverage
            decision.leverage = max(2.0, decision.leverage * wr_scale)
            decision.risk_multiplier *= wr_scale
            decision.reason += f" [WR decay {wr_scale:.2f}: recent={recent_win_rate:.0%} vs base={baseline_win_rate:.0%}]"
            logger.info(
                f"Win-rate scaling: {old_lev:.1f}x → {decision.leverage:.1f}x "
                f"(WR {recent_win_rate:.0%}/{baseline_win_rate:.0%} = {wr_scale:.2f})"
            )
        return decision

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
