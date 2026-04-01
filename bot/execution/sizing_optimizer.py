"""
Dynamic Position Sizing Optimizer — Kelly Criterion + Compound Curves.

Replaces fixed % risk with data-driven, mathematically optimal sizing.
The core insight: we have alpha (71-85% WR on proven setups), but we're
betting the minimum. Kelly says we should be sizing 3-5x larger.

Architecture:
  SizingOptimizer
    ├── per_setup_kelly()     — Rolling WR/payoff → Kelly fraction per setup
    ├── compound_curve()      — Equity milestones → risk%/leverage/max_positions
    ├── dynamic_leverage()    — Edge confidence → optimal leverage
    ├── portfolio_budget()    — Total exposure → per-trade allocation
    └── get_optimal_size()    — Master function: setup + equity → exact sizing

Usage:
    optimizer = SizingOptimizer()
    sizing = optimizer.get_optimal_size(
        setup="HYPE_BUY", equity=150.0, confidence=82.0,
        num_agree=3, regime="consolidation", is_dip_buy=True
    )
    # sizing.risk_pct, sizing.leverage, sizing.position_size_usd, etc.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger("bot.execution.sizing_optimizer")


# ─── Data Classes ───────────────────────────────────────────────────────

@dataclass
class SetupStats:
    """Rolling statistics for a specific setup (e.g., HYPE_BUY)."""
    wins: int = 0
    losses: int = 0
    total_win_pnl: float = 0.0   # sum of winning PnL %
    total_loss_pnl: float = 0.0  # sum of losing PnL % (positive = magnitude)
    streak: int = 0              # positive = win streak, negative = loss streak

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.wins / self.total

    @property
    def avg_win(self) -> float:
        if self.wins == 0:
            return 0.0
        return self.total_win_pnl / self.wins

    @property
    def avg_loss(self) -> float:
        if self.losses == 0:
            return 0.0
        return self.total_loss_pnl / self.losses

    @property
    def payoff_ratio(self) -> float:
        """Average win / average loss. Higher = better risk/reward."""
        if self.avg_loss == 0:
            return 2.0  # Default assumption
        return self.avg_win / self.avg_loss


@dataclass
class CompoundTier:
    """Parameters for a specific equity milestone."""
    min_equity: float
    max_equity: float
    kelly_fraction: float    # What fraction of full Kelly to use (0.25 = quarter)
    max_leverage: float
    max_positions: int
    daily_target: float      # Dollar target
    label: str


@dataclass
class OptimalSizing:
    """Output of the sizing optimizer — everything needed to size a trade."""
    risk_pct: float               # % of equity to risk
    risk_amount: float            # $ to risk
    leverage: float               # Optimal leverage
    position_size_usd: float      # Notional position size
    margin_required: float        # Margin needed
    kelly_full: float             # Full Kelly fraction (informational)
    kelly_used: float             # Actual Kelly fraction used
    compound_tier: str            # Which equity tier we're in
    max_loss_pct: float           # Max this trade can lose (% of equity)
    setup_wr: float               # WR used for sizing
    setup_payoff: float           # Payoff ratio used
    rationale: str                # Human-readable sizing explanation


# ─── Default Setup Priors ───────────────────────────────────────────────
# Used when we don't have enough data for a setup.
# Conservative — real data will override these quickly.

_DEFAULT_PRIORS: Dict[str, Tuple[float, float]] = {
    # (win_rate, payoff_ratio)
    # Updated 2026-03-25: edge study shows HYPE_BUY WR declining (64%→40% over 418 trades).
    # Overall 51.7% WR, PF 1.34. Prior set conservatively at current overall rate.
    "HYPE_BUY": (0.52, 1.34),   # Edge WEAKENING: 418 trades, last third 40% WR. Was 0.71.
    "SOL_SELL": (0.48, 1.0),    # PF < 1.0 across most configs. Marginal at best. Was 0.59.
    "BTC_SELL": (0.55, 1.5),    # Only marginal at 90%+ confidence.
    "BTC_BUY": (0.56, 1.4),    # 56% WR, PF 1.40 over 30 days. Not yet proven live.
    "SOL_BUY": (0.45, 1.5),    # No validated edge. Discovery only.
    "HYPE_SELL": (0.07, 1.5),  # Toxic — should never trade
}

_DEFAULT_PRIOR = (0.50, 1.5)  # Unknown setup


# ─── Compound Sizing Curve ──────────────────────────────────────────────

_COMPOUND_TIERS: List[CompoundTier] = [
    CompoundTier(0, 200, 0.25, 25.0, 2, 20.0, "bootstrap"),
    CompoundTier(200, 500, 0.33, 20.0, 3, 50.0, "growth"),
    CompoundTier(500, 1000, 0.33, 15.0, 4, 75.0, "scaling"),
    CompoundTier(1000, 5000, 0.25, 10.0, 5, 100.0, "established"),
    CompoundTier(5000, 10000, 0.20, 5.0, 6, 75.0, "preservation"),
    CompoundTier(10000, float("inf"), 0.125, 5.0, 8, 100.0, "wealth"),
]


# ─── Regime Multipliers ─────────────────────────────────────────────────

_REGIME_MULT: Dict[str, float] = {
    "trending_bull": 1.2,
    "trending_bear": 1.1,
    "trend": 1.0,
    "consolidation": 0.85,
    "range": 0.8,
    "high_volatility": 0.6,
    "panic": 0.4,
    "low_liquidity": 0.3,
    "unknown": 0.7,
}


class SizingOptimizer:
    """Dynamic position sizing based on Kelly criterion and compound curves."""

    def __init__(
        self,
        min_trades_for_kelly: int = 10,
        max_risk_pct: float = 0.30,
        min_risk_pct: float = 0.02,
        max_single_loss_pct: float = 0.15,
    ):
        self.min_trades_for_kelly = min_trades_for_kelly
        self.max_risk_pct = max_risk_pct
        self.min_risk_pct = min_risk_pct
        self.max_single_loss_pct = max_single_loss_pct

        # Per-setup rolling statistics
        self._setup_stats: Dict[str, SetupStats] = {}

        # Override from env
        self._kelly_cap = float(os.getenv("KELLY_FRACTION_CAP", "0.5"))
        self._leverage_cap = float(os.getenv("SIZING_MAX_LEVERAGE", "25"))

        logger.info(
            f"[SIZING] Optimizer initialized: kelly_cap={self._kelly_cap}, "
            f"lev_cap={self._leverage_cap}, max_risk={self.max_risk_pct:.0%}"
        )

    # ─── Public API ─────────────────────────────────────────────────

    def record_outcome(
        self, setup: str, won: bool, pnl_pct: float
    ) -> None:
        """Record a trade outcome to update rolling Kelly stats.

        Args:
            setup: Setup key (e.g., "HYPE_BUY")
            won: Whether the trade was profitable
            pnl_pct: Absolute PnL as % of entry (e.g., 3.5 for +3.5%)
        """
        if setup not in self._setup_stats:
            self._setup_stats[setup] = SetupStats()

        stats = self._setup_stats[setup]
        if won:
            stats.wins += 1
            stats.total_win_pnl += abs(pnl_pct)
            stats.streak = max(0, stats.streak) + 1
        else:
            stats.losses += 1
            stats.total_loss_pnl += abs(pnl_pct)
            stats.streak = min(0, stats.streak) - 1

        logger.debug(
            f"[SIZING] {setup} outcome: {'W' if won else 'L'} {pnl_pct:+.2f}% "
            f"→ WR={stats.win_rate:.1%} payoff={stats.payoff_ratio:.2f} "
            f"N={stats.total} streak={stats.streak}"
        )

    def get_setup_stats(self, setup: str) -> SetupStats:
        """Get current stats for a setup."""
        return self._setup_stats.get(setup, SetupStats())

    def kelly_fraction(self, setup: str) -> Tuple[float, float, float]:
        """Calculate Kelly fraction for a setup.

        Returns (full_kelly, win_rate, payoff_ratio).
        Uses rolling data if available, falls back to priors.
        """
        stats = self._setup_stats.get(setup)

        if stats is not None and stats.total >= self.min_trades_for_kelly:
            wr = stats.win_rate
            payoff = stats.payoff_ratio
        else:
            # Use prior, blended with any data we have
            prior_wr, prior_payoff = _DEFAULT_PRIORS.get(setup, _DEFAULT_PRIOR)
            if stats is not None and stats.total > 0:
                # Blend: weight data proportionally to sample size
                data_weight = min(stats.total / self.min_trades_for_kelly, 1.0)
                wr = prior_wr * (1 - data_weight) + stats.win_rate * data_weight
                payoff = prior_payoff * (1 - data_weight) + stats.payoff_ratio * data_weight
            else:
                wr = prior_wr
                payoff = prior_payoff

        # Kelly formula: f* = (p * b - q) / b
        # where p = win_rate, q = 1 - p, b = payoff_ratio
        q = 1 - wr
        if payoff <= 0:
            return 0.0, wr, payoff

        full_kelly = (wr * payoff - q) / payoff
        # Clamp to [0, kelly_cap]
        full_kelly = max(0.0, min(full_kelly, self._kelly_cap))

        return full_kelly, wr, payoff

    def get_compound_tier(self, equity: float) -> CompoundTier:
        """Get the compound curve tier for current equity."""
        for tier in _COMPOUND_TIERS:
            if tier.min_equity <= equity < tier.max_equity:
                return tier
        return _COMPOUND_TIERS[-1]

    def dynamic_leverage(
        self,
        win_rate: float,
        payoff: float,
        confidence: float,
        num_agree: int,
        regime: str,
        is_dip_buy: bool,
        tier_max_leverage: float,
    ) -> float:
        """Calculate optimal leverage from edge confidence.

        Formula: leverage = base × (WR/0.50) × sqrt(payoff) × regime_mult × agree_mult
        Capped by tier and global maximums.
        """
        base = 5.0

        # WR scaling (linear: 50% → 1.0x, 71% → 1.42x, 85% → 1.7x)
        wr_mult = max(win_rate / 0.50, 0.5)

        # Payoff scaling (sqrt: 1.5 → 1.22x, 2.0 → 1.41x)
        payoff_mult = math.sqrt(max(payoff, 0.5))

        # Regime multiplier
        regime_mult = _REGIME_MULT.get(regime, 0.7)

        # Agreement multiplier (3-agree = 1.2x, 2 = 1.0x, 1 = 0.7x)
        agree_mult = {1: 0.7, 2: 1.0, 3: 1.2}.get(num_agree, 1.0)

        # Dip-buy bonus (proven 88.5% WR on dips)
        dip_mult = 1.15 if is_dip_buy else 1.0

        # Confidence scaling (gentle: 60% → 0.9x, 80% → 1.0x, 90% → 1.05x)
        conf_mult = 0.8 + (confidence / 100.0) * 0.3

        raw_leverage = base * wr_mult * payoff_mult * regime_mult * agree_mult * dip_mult * conf_mult

        # Cap
        max_lev = min(tier_max_leverage, self._leverage_cap)
        leverage = max(1.0, min(raw_leverage, max_lev))

        return round(leverage, 1)

    def get_optimal_size(
        self,
        setup: str,
        equity: float,
        confidence: float = 70.0,
        num_agree: int = 2,
        regime: str = "unknown",
        is_dip_buy: bool = False,
        stop_width_pct: float = 0.025,
        open_positions: int = 0,
        portfolio_exposure_pct: float = 0.0,
    ) -> OptimalSizing:
        """Master sizing function. Combines Kelly + compound curve + all adjustments.

        Args:
            setup: Setup key (e.g., "HYPE_BUY")
            equity: Current account equity in USD
            confidence: Signal confidence (0-100)
            num_agree: Number of strategies agreeing
            regime: Market regime
            is_dip_buy: Whether this is a dip-buy pattern
            stop_width_pct: Stop loss width as fraction of entry (e.g., 0.025 = 2.5%)
            open_positions: Number of currently open positions
            portfolio_exposure_pct: Current total portfolio exposure as % of equity
        """
        # Step 1: Kelly fraction for this setup
        full_kelly, wr, payoff = self.kelly_fraction(setup)

        # Step 2: Compound curve tier
        tier = self.get_compound_tier(equity)

        # Step 3: Apply Kelly fraction × tier multiplier
        kelly_used = full_kelly * tier.kelly_fraction

        # Step 4: Streak adjustment
        stats = self._setup_stats.get(setup, SetupStats())
        if stats.streak <= -2:
            # Losing streak — pull back
            kelly_used *= 0.6
        # Win streak bonus REMOVED: edge study shows autocorrelation=0.090 (near random).
        # Signal clustering is marginal — after WIN: 55.2% WR, after LOSS: 46.2%.
        # Sizing should stay constant per Kelly, not chase streaks.

        # Step 5: Position count adjustment
        if open_positions >= tier.max_positions:
            kelly_used = 0.0  # No new positions
        elif open_positions >= tier.max_positions - 1:
            kelly_used *= 0.5  # Reduce for last slot

        # Step 6: Clamp risk
        risk_pct = max(self.min_risk_pct, min(kelly_used, self.max_risk_pct))

        # Step 7: Dynamic leverage
        leverage = self.dynamic_leverage(
            win_rate=wr,
            payoff=payoff,
            confidence=confidence,
            num_agree=num_agree,
            regime=regime,
            is_dip_buy=is_dip_buy,
            tier_max_leverage=tier.max_leverage,
        )

        # Step 8: Calculate position size
        risk_amount = equity * risk_pct
        if stop_width_pct > 0:
            position_size_usd = risk_amount / stop_width_pct
        else:
            position_size_usd = risk_amount * leverage

        margin_required = position_size_usd / leverage if leverage > 0 else position_size_usd

        # Step 9: Margin cap (never exceed 95% of equity)
        if margin_required > equity * 0.95:
            scale = (equity * 0.95) / margin_required
            position_size_usd *= scale
            risk_amount *= scale
            margin_required = position_size_usd / leverage

        # Step 10: Max single loss cap
        max_loss = equity * self.max_single_loss_pct
        if risk_amount > max_loss:
            scale = max_loss / risk_amount
            risk_amount *= scale
            position_size_usd *= scale
            margin_required = position_size_usd / leverage

        # Build rationale
        rationale = (
            f"Kelly={full_kelly:.1%}→{kelly_used:.1%} ({tier.label} tier, "
            f"{tier.kelly_fraction:.0%} fraction) | "
            f"WR={wr:.0%} payoff={payoff:.1f}:1 | "
            f"lev={leverage:.0f}x | "
            f"risk=${risk_amount:.2f} ({risk_pct:.1%})"
        )
        if stats.streak != 0:
            rationale += f" | streak={stats.streak:+d}"

        return OptimalSizing(
            risk_pct=round(risk_pct, 4),
            risk_amount=round(risk_amount, 2),
            leverage=leverage,
            position_size_usd=round(position_size_usd, 2),
            margin_required=round(margin_required, 2),
            kelly_full=round(full_kelly, 4),
            kelly_used=round(kelly_used, 4),
            compound_tier=tier.label,
            max_loss_pct=round(self.max_single_loss_pct, 4),
            setup_wr=round(wr, 4),
            setup_payoff=round(payoff, 2),
            rationale=rationale,
        )

    def get_stats_summary(self) -> Dict[str, Dict]:
        """Get summary of all tracked setups for logging/display."""
        summary = {}
        for setup, stats in self._setup_stats.items():
            full_kelly, wr, payoff = self.kelly_fraction(setup)
            summary[setup] = {
                "trades": stats.total,
                "wr": round(wr, 3),
                "payoff": round(payoff, 2),
                "full_kelly": round(full_kelly, 3),
                "streak": stats.streak,
            }
        return summary
