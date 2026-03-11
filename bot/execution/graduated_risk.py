"""
Graduated Drawdown Risk Reduction — Proactive Risk Management

Instead of binary circuit breakers (trading ON until threshold → trading OFF),
this module progressively reduces risk as drawdown increases:

  Drawdown   | Leverage Reduction | Risk Multiplier | Description
  -----------|-------------------|-----------------|-------------
  0-2%       | 0%                | 1.0x            | Normal trading
  2-3%       | 20%               | 0.85x           | Early warning, slight reduction
  3-5%       | 40%               | 0.70x           | Caution mode, material reduction
  5-7%       | 60%               | 0.50x           | Defensive mode, halved risk
  7-10%      | 80%               | 0.25x           | Survival mode, minimal risk
  10%+       | Circuit breaker   | 0.0x            | Full stop (existing CB)

Also tracks:
- Recovery factor: how quickly equity is recovering after drawdown
- Consecutive loss streak impact: additional reduction during streaks
- Time-in-drawdown: longer drawdowns → progressively more cautious
- Regime-aware scaling: ranging regime during drawdown → extra reduction

This replaces the binary CB approach with a smooth risk curve.
The existing CircuitBreaker remains as a hard backstop.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("bot.execution.graduated_risk")


class DrawdownBand:
    """A single drawdown band with its risk parameters."""

    def __init__(self, dd_min: float, dd_max: float,
                 leverage_reduction: float, risk_multiplier: float,
                 label: str):
        self.dd_min = dd_min
        self.dd_max = dd_max
        self.leverage_reduction = leverage_reduction  # 0.0-1.0 (fraction to reduce)
        self.risk_multiplier = risk_multiplier        # 0.0-1.0 (multiply into position size)
        self.label = label


# Default drawdown bands — progressive risk reduction
DEFAULT_BANDS = [
    DrawdownBand(0.00, 0.02, 0.00, 1.00, "normal"),
    DrawdownBand(0.02, 0.03, 0.20, 0.85, "early_warning"),
    DrawdownBand(0.03, 0.05, 0.40, 0.70, "caution"),
    DrawdownBand(0.05, 0.07, 0.60, 0.50, "defensive"),
    DrawdownBand(0.07, 0.10, 0.80, 0.25, "survival"),
    DrawdownBand(0.10, 1.00, 1.00, 0.00, "circuit_breaker"),
]


class GraduatedRiskManager:
    """
    Progressively reduces risk as drawdown increases.

    Unlike circuit breakers (binary: on/off), this provides a smooth risk curve
    that gradually reduces exposure as losses accumulate. This:
    1. Preserves capital during drawdowns without fully stopping
    2. Allows recovery trades with reduced size
    3. Prevents the "all-or-nothing" problem of traditional circuit breakers
    """

    def __init__(self, bands=None, enable_streak_penalty: bool = True,
                 enable_time_decay: bool = True,
                 enable_regime_adjustment: bool = True):
        self.bands = bands or DEFAULT_BANDS
        self.enable_streak_penalty = enable_streak_penalty
        self.enable_time_decay = enable_time_decay
        self.enable_regime_adjustment = enable_regime_adjustment

        # State tracking
        self.peak_equity: float = 0.0
        self.current_equity: float = 0.0
        self.drawdown_start_time: Optional[float] = None
        self.consecutive_losses: int = 0
        self.current_regime: str = "unknown"

        # History for recovery tracking
        self._equity_history: list = []  # (timestamp, equity) pairs
        self._max_history = 100

    def update_equity(self, equity: float, sim_time: Optional[datetime] = None):
        """Update current equity and track drawdown state."""
        self.current_equity = equity

        if equity > self.peak_equity:
            self.peak_equity = equity
            self.drawdown_start_time = None  # Reset drawdown timer

        # Track when drawdown starts
        dd = self.get_drawdown()
        if dd > 0.01 and self.drawdown_start_time is None:
            self.drawdown_start_time = time.time()

        # Record equity history
        ts = (sim_time or datetime.now(timezone.utc)).timestamp()
        self._equity_history.append((ts, equity))
        if len(self._equity_history) > self._max_history:
            self._equity_history = self._equity_history[-self._max_history:]

    def record_trade(self, pnl: float):
        """Record a trade outcome for streak tracking."""
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def set_regime(self, regime: str):
        """Update current market regime for regime-aware adjustments."""
        self.current_regime = regime

    def get_drawdown(self) -> float:
        """Get current drawdown as a fraction (0.0 = no drawdown, 0.10 = 10%)."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)

    def get_band(self) -> DrawdownBand:
        """Get the current drawdown band."""
        dd = self.get_drawdown()
        for band in self.bands:
            if band.dd_min <= dd < band.dd_max:
                return band
        return self.bands[-1]  # Worst case: circuit breaker band

    def get_risk_adjustment(self) -> Dict[str, Any]:
        """
        Compute the full risk adjustment based on drawdown + modifiers.

        Returns:
            Dict with:
            - leverage_reduction: fraction to reduce leverage (0.0 = no reduction)
            - risk_multiplier: multiply into position size (1.0 = full size)
            - band_label: human-readable band name
            - drawdown_pct: current drawdown percentage
            - modifiers: dict of applied adjustments
        """
        dd = self.get_drawdown()
        band = self.get_band()

        base_lev_reduction = band.leverage_reduction
        base_risk_mult = band.risk_multiplier

        modifiers = {}

        # Modifier 1: Consecutive loss streak penalty
        streak_penalty = 0.0
        if self.enable_streak_penalty and self.consecutive_losses >= 3:
            # Each loss beyond 2 adds 5% reduction (capped at 25%)
            streak_penalty = min(0.25, (self.consecutive_losses - 2) * 0.05)
            modifiers["streak_penalty"] = streak_penalty

        # Modifier 2: Time-in-drawdown decay
        time_penalty = 0.0
        if self.enable_time_decay and self.drawdown_start_time is not None:
            hours_in_dd = (time.time() - self.drawdown_start_time) / 3600
            if hours_in_dd > 6:
                # After 6h in drawdown, each additional 6h adds 5% reduction (capped at 20%)
                time_penalty = min(0.20, ((hours_in_dd - 6) / 6) * 0.05)
                modifiers["time_in_drawdown_h"] = hours_in_dd
                modifiers["time_penalty"] = time_penalty

        # Modifier 3: Regime-aware adjustment
        regime_penalty = 0.0
        if self.enable_regime_adjustment and dd > 0.02:
            # During drawdown, ranging/panic regimes get extra reduction
            if self.current_regime in ("range", "unknown"):
                regime_penalty = 0.10  # 10% extra reduction in ranging
                modifiers["regime_penalty"] = regime_penalty
            elif self.current_regime == "panic":
                regime_penalty = 0.20  # 20% extra in panic
                modifiers["regime_penalty"] = regime_penalty

        # Combine all modifiers
        total_lev_reduction = min(1.0, base_lev_reduction + streak_penalty + time_penalty + regime_penalty)
        total_risk_mult = max(0.0, base_risk_mult * (1 - streak_penalty - time_penalty - regime_penalty))

        # Clamp
        total_risk_mult = max(0.0, min(1.0, total_risk_mult))

        return {
            "leverage_reduction": total_lev_reduction,
            "risk_multiplier": total_risk_mult,
            "band_label": band.label,
            "drawdown_pct": dd * 100,
            "consecutive_losses": self.consecutive_losses,
            "modifiers": modifiers,
        }

    def apply_to_leverage(self, raw_leverage: float) -> float:
        """Apply graduated risk reduction to a leverage value."""
        adj = self.get_risk_adjustment()
        reduced = raw_leverage * (1 - adj["leverage_reduction"])
        # Always allow minimum leverage of 1.0 unless in circuit breaker band
        if adj["band_label"] == "circuit_breaker":
            return 0.0
        return max(1.0, reduced)

    def apply_to_risk_multiplier(self, raw_multiplier: float) -> float:
        """Apply graduated risk reduction to a risk multiplier."""
        adj = self.get_risk_adjustment()
        return raw_multiplier * adj["risk_multiplier"]

    def get_recovery_factor(self) -> float:
        """
        Compute recovery factor: how quickly equity is recovering.
        1.0 = recovering well, 0.0 = still declining, <0 = accelerating losses.
        """
        if len(self._equity_history) < 5:
            return 0.5  # Insufficient data, neutral

        recent = [e for _, e in self._equity_history[-10:]]
        if len(recent) < 3:
            return 0.5

        # Compare recent trend to drawdown direction
        first_half = sum(recent[:len(recent)//2]) / (len(recent)//2)
        second_half = sum(recent[len(recent)//2:]) / (len(recent) - len(recent)//2)

        if first_half <= 0:
            return 0.5

        recovery_ratio = (second_half - first_half) / first_half
        # Normalize to 0-1 range
        return max(0.0, min(1.0, 0.5 + recovery_ratio * 10))

    def should_skip_trade(self) -> Tuple[bool, str]:
        """
        Check if the graduated risk manager recommends skipping this trade.
        Returns (should_skip, reason).
        """
        adj = self.get_risk_adjustment()

        if adj["band_label"] == "circuit_breaker":
            return True, f"Drawdown {adj['drawdown_pct']:.1f}% — circuit breaker band"

        if adj["risk_multiplier"] < 0.1:
            return True, f"Risk multiplier {adj['risk_multiplier']:.2f} — effectively zero"

        return False, ""

    def get_status(self) -> Dict[str, Any]:
        """Get full status for logging/display."""
        adj = self.get_risk_adjustment()
        return {
            "drawdown_pct": adj["drawdown_pct"],
            "band": adj["band_label"],
            "leverage_reduction": adj["leverage_reduction"],
            "risk_multiplier": adj["risk_multiplier"],
            "consecutive_losses": self.consecutive_losses,
            "recovery_factor": self.get_recovery_factor(),
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            "modifiers": adj["modifiers"],
        }

    def get_llm_context(self) -> str:
        """Generate context string for LLM agent prompts."""
        adj = self.get_risk_adjustment()
        if adj["band_label"] == "normal":
            return ""  # No drawdown, no context needed

        lines = [f"DRAWDOWN ALERT: {adj['drawdown_pct']:.1f}% drawdown, "
                 f"band={adj['band_label']}, risk_mult={adj['risk_multiplier']:.2f}"]

        if self.consecutive_losses >= 3:
            lines.append(f"  Loss streak: {self.consecutive_losses} consecutive losses")

        rf = self.get_recovery_factor()
        if rf < 0.3:
            lines.append(f"  Recovery: WEAK ({rf:.2f}) — equity still declining")
        elif rf > 0.7:
            lines.append(f"  Recovery: STRONG ({rf:.2f}) — equity recovering")

        for key, val in adj["modifiers"].items():
            if "penalty" in key:
                lines.append(f"  Modifier: {key}={val:.2f}")

        return "\n".join(lines)
