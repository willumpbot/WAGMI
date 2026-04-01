"""
MFE-Aware Exit Intelligence — Data-driven exit decisions based on
Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).

Key insight: every symbol has a *typical* move size within a holding window.
If uPnL already exceeds the median MFE, the position has captured more
than most trades ever will — take the gift.  Conversely, if drawdown
exceeds the median MAE after several hours, recovery is unlikely.

MFE/MAE percentile data sourced from 2h holding-window study on
Hyperliquid SHORT positions (March 2026).

Recommendation hierarchy:
  EXIT_NOW       — close immediately (loser past recovery window)
  TAKE_PROFIT    — close at market (captured > 2x median MFE)
  TIGHTEN_STOP   — move SL to breakeven or better (fading momentum)
  HOLD           — no action needed
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger("bot.execution.mfe_exit")

# ─── MFE / MAE percentile constants (2h window, SHORT side) ─────────
# Format: {symbol: {"mfe_p50": %, "mfe_p75": %, "mae_p50": %, "mae_p75": %}}
# Values are in *percent* (0.38 means 0.38%).

MFE_MAE_DATA: Dict[str, Dict[str, float]] = {
    "BTC": {
        "mfe_p50": 0.38, "mfe_p75": 0.70,
        "mae_p50": 0.37, "mae_p75": 0.72,
    },
    "SOL": {
        "mfe_p50": 0.51, "mfe_p75": 0.91,
        "mae_p50": 0.47, "mae_p75": 0.96,
    },
    "ETH": {
        "mfe_p50": 0.44, "mfe_p75": 0.90,
        "mae_p50": 0.50, "mae_p75": 0.90,
    },
    "HYPE": {
        "mfe_p50": 0.78, "mfe_p75": 1.37,
        "mae_p50": 0.77, "mae_p75": 1.34,
    },
}

# Fallback for unlisted symbols — conservative average of BTC/ETH
DEFAULT_MFE_MAE = {
    "mfe_p50": 0.40, "mfe_p75": 0.80,
    "mae_p50": 0.42, "mae_p75": 0.80,
}


@dataclass
class ExitRecommendation:
    """Output of the MFE exit advisor."""
    action: str             # HOLD | TAKE_PROFIT | TIGHTEN_STOP | EXIT_NOW
    urgency: str = "low"    # low | medium | high | critical
    reason: str = ""
    upnl_pct: float = 0.0   # current uPnL as % of entry
    mfe_ratio: float = 0.0   # uPnL / median MFE (>1 = above median)
    mae_ratio: float = 0.0   # |drawdown| / median MAE (>1 = deeper than typical)
    hold_hours: float = 0.0


class MFEExitAdvisor:
    """
    Data-driven exit intelligence using MFE/MAE percentile benchmarks.

    Parameters
    ----------
    take_profit_mfe_mult : float
        Take profit when uPnL > this * median MFE.  Default 2.0.
    tighten_mfe_mult : float
        Tighten stop when uPnL > this * median MFE with fading momentum.
        Default 1.5.
    loser_timeout_hours : float
        Exit losing positions older than this.  Default 4.0.
    deep_loss_timeout_hours : float
        Exit positions in deep drawdown (>1x MAE) after this many hours.
        Default 2.0.
    volume_spike_mult : float
        Volume spike threshold for momentum-cascade HOLD override.
        Default 3.0.
    """

    def __init__(
        self,
        take_profit_mfe_mult: float = 2.0,
        tighten_mfe_mult: float = 1.5,
        loser_timeout_hours: float = 4.0,
        deep_loss_timeout_hours: float = 2.0,
        volume_spike_mult: float = 3.0,
    ):
        self.take_profit_mfe_mult = take_profit_mfe_mult
        self.tighten_mfe_mult = tighten_mfe_mult
        self.loser_timeout_hours = loser_timeout_hours
        self.deep_loss_timeout_hours = deep_loss_timeout_hours
        self.volume_spike_mult = volume_spike_mult

    # ─── public API ─────────────────────────────────────────────────

    def evaluate(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        open_timestamp: float,
        leverage: float = 1.0,
        current_volume: Optional[float] = None,
        avg_volume: Optional[float] = None,
    ) -> ExitRecommendation:
        """
        Evaluate an open position and return an exit recommendation.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "BTC", "SOL", "HYPE").
        side : str
            "BUY" (long) or "SELL" (short).
        entry_price : float
            Position entry price.
        current_price : float
            Current market price.
        open_timestamp : float
            Unix timestamp when the position was opened.
        leverage : float
            Position leverage (used for logging context, not decision logic).
        current_volume : float, optional
            Current candle volume.
        avg_volume : float, optional
            Average volume over recent candles.

        Returns
        -------
        ExitRecommendation
        """
        # Normalise symbol (strip /USDT, -PERP, etc.)
        sym = self._normalise_symbol(symbol)
        data = MFE_MAE_DATA.get(sym, DEFAULT_MFE_MAE)

        # Calculate uPnL percentage
        if side.upper() == "BUY":
            upnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            upnl_pct = ((entry_price - current_price) / entry_price) * 100

        hold_hours = (time.time() - open_timestamp) / 3600.0

        mfe_p50 = data["mfe_p50"]
        mae_p50 = data["mae_p50"]

        mfe_ratio = upnl_pct / mfe_p50 if mfe_p50 > 0 else 0.0
        mae_ratio = abs(upnl_pct) / mae_p50 if (upnl_pct < 0 and mae_p50 > 0) else 0.0

        base = ExitRecommendation(
            action="HOLD",
            upnl_pct=upnl_pct,
            mfe_ratio=mfe_ratio,
            mae_ratio=mae_ratio,
            hold_hours=hold_hours,
        )

        # ── Rule 1: Volume spike + price in our favor → HOLD (momentum cascade)
        if self._has_volume_spike(current_volume, avg_volume) and upnl_pct > 0:
            base.action = "HOLD"
            base.reason = (
                f"Volume spike ({current_volume:.0f} vs avg {avg_volume:.0f}) "
                f"with positive uPnL — momentum cascade, let it run"
            )
            logger.info(f"[MFE-Exit] {sym} HOLD — {base.reason}")
            return base

        # ── Rule 2: uPnL > 2x median MFE → TAKE_PROFIT
        if upnl_pct > 0 and mfe_ratio >= self.take_profit_mfe_mult:
            base.action = "TAKE_PROFIT"
            base.urgency = "high"
            base.reason = (
                f"uPnL {upnl_pct:.3f}% is {mfe_ratio:.1f}x the median MFE "
                f"({mfe_p50:.2f}%) — captured more than typical, take profit"
            )
            logger.info(f"[MFE-Exit] {sym} TAKE_PROFIT — {base.reason}")
            return base

        # ── Rule 3: uPnL > 1.5x median MFE + fading momentum → TIGHTEN_STOP
        if upnl_pct > 0 and mfe_ratio >= self.tighten_mfe_mult:
            momentum_fading = self._is_momentum_fading(current_volume, avg_volume)
            if momentum_fading:
                base.action = "TIGHTEN_STOP"
                base.urgency = "medium"
                base.reason = (
                    f"uPnL {upnl_pct:.3f}% is {mfe_ratio:.1f}x median MFE "
                    f"and momentum fading — tighten stop to lock gains"
                )
                logger.info(f"[MFE-Exit] {sym} TIGHTEN_STOP — {base.reason}")
                return base

        # ── Rule 4: Open > 2h AND drawdown > 1x median MAE → EXIT_NOW
        if (
            hold_hours >= self.deep_loss_timeout_hours
            and upnl_pct < 0
            and mae_ratio >= 1.0
        ):
            base.action = "EXIT_NOW"
            base.urgency = "critical"
            base.reason = (
                f"Open {hold_hours:.1f}h with drawdown {upnl_pct:.3f}% "
                f"({mae_ratio:.1f}x median MAE {mae_p50:.2f}%) — "
                f"deeper than typical, cut loss"
            )
            logger.info(f"[MFE-Exit] {sym} EXIT_NOW — {base.reason}")
            return base

        # ── Rule 5: Open > 4h AND still losing → EXIT_NOW
        if hold_hours >= self.loser_timeout_hours and upnl_pct < 0:
            base.action = "EXIT_NOW"
            base.urgency = "high"
            base.reason = (
                f"Loser open {hold_hours:.1f}h with uPnL {upnl_pct:.3f}% — "
                f"positions that haven't recovered by {self.loser_timeout_hours}h rarely do"
            )
            logger.info(f"[MFE-Exit] {sym} EXIT_NOW — {base.reason}")
            return base

        # ── Default: HOLD
        base.reason = (
            f"uPnL {upnl_pct:.3f}% after {hold_hours:.1f}h — "
            f"within normal MFE/MAE range, hold"
        )
        logger.debug(f"[MFE-Exit] {sym} HOLD — {base.reason}")
        return base

    # ─── convenience function (module-level wrapper below) ──────────

    def should_take_profit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        side: str,
        leverage: float = 1.0,
        hold_hours: float = 0.0,
    ) -> bool:
        """
        Quick check: should this position take profit now?

        Uses a synthetic open_timestamp derived from hold_hours so the
        full evaluate() logic applies without needing a real timestamp.
        """
        open_ts = time.time() - (hold_hours * 3600)
        rec = self.evaluate(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            open_timestamp=open_ts,
            leverage=leverage,
        )
        return rec.action in ("TAKE_PROFIT", "EXIT_NOW")

    # ─── helpers ────────────────────────────────────────────────────

    def _has_volume_spike(
        self, current_volume: Optional[float], avg_volume: Optional[float]
    ) -> bool:
        """True if current volume is a significant spike above average."""
        if current_volume is None or avg_volume is None:
            return False
        if avg_volume <= 0:
            return False
        return current_volume >= avg_volume * self.volume_spike_mult

    def _is_momentum_fading(
        self, current_volume: Optional[float], avg_volume: Optional[float]
    ) -> bool:
        """
        Heuristic for fading momentum: volume is below average.
        When volume data is unavailable, assume momentum *could* be fading
        (conservative — better to tighten than miss the exit).
        """
        if current_volume is None or avg_volume is None:
            return True  # conservative: assume fading when no data
        if avg_volume <= 0:
            return True
        return current_volume < avg_volume

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """Strip exchange suffixes: 'BTC/USDT:USDT' → 'BTC', 'SOL-PERP' → 'SOL'."""
        sym = symbol.upper()
        for suffix in ("/USDT:USDT", "/USDT", "-PERP", "-USD", "USDT", "USD"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
                break
        return sym


# ─── Module-level convenience function ──────────────────────────────

_default_advisor = MFEExitAdvisor()


def should_take_profit(
    symbol: str,
    entry: float,
    current_price: float,
    side: str,
    leverage: float = 1.0,
    hold_hours: float = 0.0,
) -> bool:
    """
    Module-level convenience: should this position take profit?

    Returns True if the MFE advisor recommends TAKE_PROFIT or EXIT_NOW.
    """
    return _default_advisor.should_take_profit(
        symbol=symbol,
        entry_price=entry,
        current_price=current_price,
        side=side,
        leverage=leverage,
        hold_hours=hold_hours,
    )


def get_exit_recommendation(
    symbol: str,
    side: str,
    entry_price: float,
    current_price: float,
    open_timestamp: float,
    leverage: float = 1.0,
    current_volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
) -> ExitRecommendation:
    """Module-level convenience: get full exit recommendation."""
    return _default_advisor.evaluate(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        open_timestamp=open_timestamp,
        leverage=leverage,
        current_volume=current_volume,
        avg_volume=avg_volume,
    )
