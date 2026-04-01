"""
Conviction-Based Leverage Sizer — Precision sizing on high-confluence setups.

PRINCIPLE: Precision entry = tight stop = high leverage at SAME dollar risk.
A 0.5% stop at 20x is the SAME dollar risk as a 2.5% stop at 4x, but 5x
more upside. The key is matching leverage to entry precision.

TWO ENTRY MODES (data-driven from 500-candle noise floor analysis, 2026-03-25):

  MODE A: STANDARD (1h entries, auto or manual):
    Confluence-based leverage with 1h noise floor stops.
    1 confluence:  5x  (minimum, unproven level)
    2 confluences: 8x  (two independent reasons)
    3 confluences: 10x (strong level)
    4 confluences: 12x (very strong)
    5+ confluences: 15x (fortress level)

  MODE B: PRECISION (5m-timed entries, manual only):
    5m entry timing at structure = 3-6x tighter stops = higher leverage
    at the SAME dollar risk. Requires 5m candle timing + volume confirmation.
    1 confluence:  8x  (5m timing, basic level)
    2 confluences: 12x (5m + 2 reasons)
    3 confluences: 15x (5m + strong confluence)
    4 confluences: 18x (5m + very strong)
    5+ confluences: 20x (5m + fortress + vol confirm + MTF aligned)

  NOISE FLOOR DATA (1h candles, 500 samples):
    HYPE: P75 wick = 0.98%, P90 = 1.59%. Min viable 1h SL = 1.0%
    BTC:  P75 wick = 0.51%, P90 = 0.80%. Min viable 1h SL = 0.5%
    SOL:  P75 wick = 0.66%, P90 = 0.96%. Min viable 1h SL = 0.7%

  STOP WIDTH EDGE (simulated, 1h entries, 1.5:1 R:R, 6h hold):
    0.3% SL: WR 28-37% -> NEGATIVE edge (too tight, noise kills it)
    0.5% SL: WR 37-39% -> MARGINAL (only BTC survives)
    0.8% SL: WR 41-44% -> POSITIVE edge appears (sweet spot starts)
    1.0% SL: WR 42-46% -> SOLID edge for HYPE/BTC
    1.5% SL: WR 46-48% -> BEST overall WR, moderate leverage

  RISK OF RUIN (MC 1000x100 at 52% WR, 1.5:1 R:R, 2% risk/trade):
    5x:  0% ruin, median +76% equity, max DD 13.5%
    10x: 0% ruin at ideal WR, but WR degrades -3% from tighter stops
    15x: 0% ruin at ideal, WR degrades -6%, median equity +31%
    20x: 0% ruin at ideal, WR degrades -10%, median equity +7%
    25x: WR degrades -15%, median LOSS of -16%, max DD 30%

  CRITICAL RULE: Risk per trade DECREASES as leverage increases.
    5-8x:  2.0% equity, 10-12x: 1.5%, 15x: 1.0%, 20x: 0.75%, 25x: 0.5%

Modifiers (multiplicative on base leverage):
  Multi-TF aligned:          +20%
  Prime hours (18-06 UTC):   +10%
  Optimal vol regime:        +10%
  Counter-trend:             -50% (or skip)
  After 2+ consecutive wins: +15% (momentum)
  After 2+ consecutive losses: -30% (caution)

EXAMPLE (HYPE BUY at $40.00, 5 confluences, $100 account):
  STANDARD (1h): 15x lev, SL $39.60 (1.0%), risk 2.5% = $2.50
    Win +$3.75, Loss -$2.50, R:R 1.5:1
  PRECISION (5m): 20x lev, SL $39.85 (0.375%), risk 0.75% = $0.75
    Win +$3.00, Loss -$0.75, R:R 4.0:1
  PRECISION same $risk: 20x, SL $39.85, risk 2.0% = $2.00
    Win +$8.00, Loss -$2.00, R:R 4.0:1 (2.67x more profit, same risk!)
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.manual.conviction_sizer")

# ── Confluence -> Leverage mapping (STANDARD mode: 1h entries) ────────
CONFLUENCE_LEVERAGE = {
    1: 5.0,
    2: 8.0,
    3: 10.0,
    4: 12.0,
    5: 15.0,   # 5+ confluences = fortress level
}

# ── Confluence -> Leverage mapping (PRECISION mode: 5m-timed entries) ─
# Data-driven: 5m entries allow 3-6x tighter stops (noise floor analysis
# 2026-03-25). Higher leverage is safe because the STOP is tighter, not
# because we're taking more dollar risk.
PRECISION_CONFLUENCE_LEVERAGE = {
    1: 8.0,    # 5m timing alone = moderate confidence
    2: 12.0,   # 5m + 2 reasons = strong
    3: 15.0,   # 5m + 3 confluences = very strong
    4: 18.0,   # 5m + 4 confluences + vol = near-max
    5: 20.0,   # 5m + 5+ conf + vol + MTF = fortress precision
}

# ── Confluence -> Risk % mapping ──────────────────────────────────────
# STANDARD mode: risk scales UP with conviction
CONFLUENCE_RISK_PCT = {
    1: 0.010,   # 1.0%
    2: 0.010,   # 1.0%
    3: 0.015,   # 1.5%
    4: 0.020,   # 2.0%
    5: 0.025,   # 2.5% (max for small accounts)
}

# PRECISION mode: risk DECREASES with leverage (same dollar risk, tighter stop)
# This is the key insight: higher leverage + lower risk% = same $ at risk
# but the R:R improves dramatically because TP distance stays the same
PRECISION_RISK_PCT = {
    1: 0.015,   # 1.5% at 8x  -> moderate position
    2: 0.012,   # 1.2% at 12x -> slightly reduced
    3: 0.010,   # 1.0% at 15x -> controlled
    4: 0.008,   # 0.8% at 18x -> tight risk
    5: 0.007,   # 0.7% at 20x -> precision risk (same $ as 2% at 5x)
}

# ── Minimum stop widths by asset (from noise floor analysis) ─────────
# Below these thresholds, random noise will stop you out.
# Values are P75 of 1h close-to-wick distance (500 candle sample).
ASSET_MIN_STOP_PCT = {
    "HYPE": 0.0098,   # 0.98% — high vol alt
    "BTC":  0.0051,   # 0.51% — large cap, tighter
    "SOL":  0.0066,   # 0.66% — mid vol
}
# For 5m precision entries, stops can be tighter (behind 5m structure)
ASSET_MIN_STOP_PCT_5M = {
    "HYPE": 0.0040,   # 0.40% — practical 5m floor (not theoretical 0.15%)
    "BTC":  0.0025,   # 0.25% — 5m BTC structure
    "SOL":  0.0030,   # 0.30% — 5m SOL structure
}

# ── Absolute caps ─────────────────────────────────────────────────────
MAX_LEVERAGE = 20.0        # Hard cap after all modifiers (standard)
MAX_LEVERAGE_PRECISION = 25.0  # Hard cap for precision mode
MIN_LEVERAGE = 3.0         # Never go below this
MAX_RISK_PCT = 0.030       # 3.0% absolute max risk
MIN_RISK_PCT = 0.005       # 0.5% absolute min risk

# ── Vol regime optimal bands (from edge study) ────────────────────────
OPTIMAL_VOL_BANDS = {
    "HYPE": (1.40, 1.69),   # ATR% sweet spot: PF 3.51
    "SOL":  (0.80, 0.98),   # ATR% sweet spot: PF 1.75
    "BTC":  (0.92, 1.03),   # ATR% sweet spot: PF 3.13
}

# ── Log path ──────────────────────────────────────────────────────────
_LOG_DIR = os.path.join("data", "manual")
_LOG_PATH = os.path.join(_LOG_DIR, "conviction_sizing.jsonl")


@dataclass
class ConvictionResult:
    """Output of the conviction sizer."""
    leverage: float           # Final leverage after all modifiers
    risk_pct: float           # Risk as fraction of equity (e.g. 0.025 = 2.5%)
    risk_amount: float        # Dollar risk
    position_notional: float  # Total position value (equity * leverage fraction)
    qty: float                # Asset quantity at entry price
    margin_required: float    # Margin = notional / leverage

    # Projected outcomes
    pnl_if_tp: float          # Dollar profit if TP hit
    pnl_if_sl: float          # Dollar loss if SL hit (negative)
    rr_ratio: float           # Reward:Risk ratio

    # Breakdown
    base_leverage: float      # Before modifiers
    modifiers_applied: List[str]  # Which modifiers were applied
    confluence_count: int
    confluence_sources: List[str]
    conviction_tier: str      # "minimum" / "moderate" / "strong" / "very_strong" / "fortress"
    precision_mode: bool = False  # True if 5m-timed precision entry

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """One-line summary for alerts."""
        mode = "PREC" if self.precision_mode else "STD"
        return (
            f"{self.conviction_tier.upper()} [{mode}] | "
            f"{self.confluence_count} confluences | "
            f"{self.leverage:.1f}x lev | "
            f"{self.risk_pct*100:.1f}% risk (${self.risk_amount:.2f}) | "
            f"notional ${self.position_notional:.0f} | "
            f"TP +${self.pnl_if_tp:.2f} / SL -${abs(self.pnl_if_sl):.2f} | "
            f"R:R {self.rr_ratio:.2f}"
        )


def _tier_name(confluences: int) -> str:
    if confluences >= 5:
        return "fortress"
    elif confluences == 4:
        return "very_strong"
    elif confluences == 3:
        return "strong"
    elif confluences == 2:
        return "moderate"
    else:
        return "minimum"


class ConvictionSizer:
    """
    Conviction-based leverage and sizing engine.

    Takes a trade setup (with confluence data) and returns precise
    leverage, risk, and position sizing calibrated to conviction level.
    """

    def __init__(
        self,
        max_leverage: float = MAX_LEVERAGE,
        min_leverage: float = MIN_LEVERAGE,
        max_risk_pct: float = MAX_RISK_PCT,
        min_risk_pct: float = MIN_RISK_PCT,
        precision_mode: bool = False,
        log_path: Optional[str] = None,
    ):
        self.max_leverage = MAX_LEVERAGE_PRECISION if precision_mode else max_leverage
        self.min_leverage = min_leverage
        self.max_risk_pct = max_risk_pct
        self.min_risk_pct = min_risk_pct
        self.precision_mode = precision_mode
        self._log_path = log_path or _LOG_PATH
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

        # Streak tracking (updated externally via record_outcome)
        self._recent_outcomes: List[bool] = []  # True=win, False=loss
        self._max_streak_window = 10
        # High-leverage streak breaker: if 2 consecutive losses at >12x,
        # force base leverage for next 3 trades (prevents tilt cascading)
        self._high_lev_losses: int = 0  # consecutive high-lev losses
        self._forced_base_trades: int = 0  # trades remaining at forced base

    # ── Public API ────────────────────────────────────────────────────

    def size(
        self,
        equity: float,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        confluences: int,
        confluence_sources: Optional[List[str]] = None,
        symbol: str = "",
        side: str = "BUY",
        multi_tf_aligned: bool = False,
        regime: str = "unknown",
        atr: Optional[float] = None,
        utc_hour: Optional[int] = None,
        precision_entry: Optional[bool] = None,
    ) -> Optional[ConvictionResult]:
        """
        Calculate conviction-based leverage and position size.

        Args:
            equity: Current account equity in USD
            entry_price: Entry price
            sl_price: Stop loss price
            tp_price: Take profit price
            confluences: Number of confluence factors (1-5+)
            confluence_sources: List of source names (e.g. ["BB_Mid", "EMA50"])
            symbol: Trading symbol (e.g. "HYPE", "SOL")
            side: "BUY" or "SELL"
            multi_tf_aligned: Whether multiple timeframes agree
            regime: Current market regime string
            atr: Current ATR value (for vol regime check)
            utc_hour: UTC hour override (for testing)
            precision_entry: Override precision mode for this trade (None = use instance default)

        Returns:
            ConvictionResult with full sizing breakdown, or None if trade
            should be skipped (e.g. counter-trend).
        """
        if equity <= 0 or entry_price <= 0:
            logger.warning(f"[CONVICTION] Invalid equity={equity} or entry={entry_price}")
            return None

        # Validate SL is on correct side
        if side == "BUY" and sl_price >= entry_price:
            logger.warning(f"[CONVICTION] BUY but SL {sl_price} >= entry {entry_price}")
            return None
        if side == "SELL" and sl_price <= entry_price:
            logger.warning(f"[CONVICTION] SELL but SL {sl_price} <= entry {entry_price}")
            return None

        # Determine if this is a precision entry
        is_precision = precision_entry if precision_entry is not None else self.precision_mode

        # Stop width
        stop_width = abs(entry_price - sl_price)
        stop_width_pct = stop_width / entry_price

        # Validate against asset-specific noise floor
        sym_upper = symbol.upper() if symbol else ""
        if is_precision:
            min_stop = ASSET_MIN_STOP_PCT_5M.get(sym_upper, 0.0025)
        else:
            min_stop = ASSET_MIN_STOP_PCT.get(sym_upper, 0.003)

        if stop_width_pct < min_stop:
            logger.warning(
                f"[CONVICTION] Stop too tight for {sym_upper}: "
                f"{stop_width_pct*100:.3f}% < noise floor {min_stop*100:.2f}% "
                f"({'precision' if is_precision else 'standard'} mode)"
            )
            return None

        # TP distance
        tp_dist = abs(tp_price - entry_price)
        rr_ratio = tp_dist / stop_width if stop_width > 0 else 0

        # Clamp confluences to 1-5 range for lookup
        conf_clamped = max(1, min(5, confluences))
        confluence_sources = confluence_sources or []

        # ── 1. Base leverage from confluence count ──
        if is_precision:
            base_leverage = PRECISION_CONFLUENCE_LEVERAGE[conf_clamped]
        else:
            base_leverage = CONFLUENCE_LEVERAGE[conf_clamped]

        # ── 2. Apply modifiers ──
        modifier = 1.0
        modifiers_applied = []

        # Multi-timeframe alignment: +20%
        if multi_tf_aligned:
            modifier *= 1.20
            modifiers_applied.append("multi_tf_aligned(+20%)")

        # Prime hours (18-06 UTC): +10%
        hour = utc_hour if utc_hour is not None else datetime.now(timezone.utc).hour
        if hour >= 18 or hour < 6:
            modifier *= 1.10
            modifiers_applied.append(f"prime_hours({hour}UTC)(+10%)")

        # Optimal vol regime: +10%
        if atr is not None and entry_price > 0 and symbol:
            atr_pct = (atr / entry_price) * 100.0
            band = OPTIMAL_VOL_BANDS.get(symbol.upper())
            if band and band[0] <= atr_pct <= band[1]:
                modifier *= 1.10
                modifiers_applied.append(f"optimal_vol({atr_pct:.2f}%)(+10%)")

        # Counter-trend: -50% or skip
        is_counter = self._is_counter_trend(side, regime)
        if is_counter:
            modifier *= 0.50
            modifiers_applied.append(f"counter_trend({regime})(-50%)")

        # Win/loss streak modifiers
        streak_mod, streak_desc = self._get_streak_modifier()
        if streak_mod != 1.0:
            modifier *= streak_mod
            modifiers_applied.append(streak_desc)

        # Precision mode modifier
        if is_precision:
            modifiers_applied.append("precision_5m_entry")

        # ── 3. Final leverage ──
        max_lev = MAX_LEVERAGE_PRECISION if is_precision else self.max_leverage
        final_leverage = base_leverage * modifier
        final_leverage = round(
            max(self.min_leverage, min(max_lev, final_leverage)), 1
        )

        # High-leverage streak breaker: force base leverage after consecutive
        # high-lev losses to prevent tilt cascading
        if self._forced_base_trades > 0:
            final_leverage = min(final_leverage, 5.0)
            modifiers_applied.append(f"forced_base({self._forced_base_trades}_remaining)")
            self._forced_base_trades -= 1

        # ── 4. Risk % from confluence ──
        if is_precision:
            risk_pct = PRECISION_RISK_PCT[conf_clamped]
        else:
            risk_pct = CONFLUENCE_RISK_PCT[conf_clamped]
        # Apply streak modifier to risk too (cautious after losses)
        if streak_mod < 1.0:
            risk_pct *= max(0.5, streak_mod)
        risk_pct = max(self.min_risk_pct, min(self.max_risk_pct, risk_pct))

        # ── 5. Position sizing ──
        risk_amount = equity * risk_pct
        # qty = risk_amount / stop_width (how many units we can lose stop_width on)
        qty = risk_amount / stop_width if stop_width > 0 else 0
        position_notional = qty * entry_price
        margin_required = position_notional / final_leverage if final_leverage > 0 else position_notional

        # Sanity: margin cannot exceed equity
        if margin_required > equity:
            # Scale down qty to fit within equity margin
            scale = equity / margin_required
            qty *= scale
            position_notional = qty * entry_price
            margin_required = position_notional / final_leverage if final_leverage > 0 else position_notional
            risk_amount = qty * stop_width
            risk_pct = risk_amount / equity if equity > 0 else 0
            modifiers_applied.append(f"margin_capped(scale={scale:.2f})")

        # ── 6. Projected PnL ──
        if side == "BUY":
            pnl_if_tp = qty * (tp_price - entry_price)
            pnl_if_sl = -qty * (entry_price - sl_price)
        else:
            pnl_if_tp = qty * (entry_price - tp_price)
            pnl_if_sl = -qty * (sl_price - entry_price)

        result = ConvictionResult(
            leverage=final_leverage,
            risk_pct=risk_pct,
            risk_amount=round(risk_amount, 2),
            position_notional=round(position_notional, 2),
            qty=round(qty, 6),
            margin_required=round(margin_required, 2),
            pnl_if_tp=round(pnl_if_tp, 2),
            pnl_if_sl=round(pnl_if_sl, 2),
            rr_ratio=round(rr_ratio, 2),
            base_leverage=base_leverage,
            modifiers_applied=modifiers_applied,
            confluence_count=confluences,
            confluence_sources=list(confluence_sources),
            conviction_tier=_tier_name(confluences),
            precision_mode=is_precision,
        )

        self._log_sizing(symbol, side, equity, entry_price, result)

        logger.info(
            f"[CONVICTION] {symbol} {side} | {result.summary()}"
        )

        return result

    def record_outcome(self, won: bool, leverage_used: float = 0) -> None:
        """Record a trade outcome (win/loss) for streak tracking.

        Args:
            won: True if trade was profitable, False otherwise.
            leverage_used: The leverage used on this trade (for streak breaker).
        """
        self._recent_outcomes.append(won)
        if len(self._recent_outcomes) > self._max_streak_window:
            self._recent_outcomes = self._recent_outcomes[-self._max_streak_window:]

        # High-leverage streak breaker
        if not won and leverage_used > 12.0:
            self._high_lev_losses += 1
            if self._high_lev_losses >= 2:
                self._forced_base_trades = 3
                self._high_lev_losses = 0
                logger.warning(
                    f"[CONVICTION] HIGH-LEV STREAK BREAKER: 2 consecutive losses "
                    f"at >{12}x leverage. Forcing base leverage for next 3 trades."
                )
        else:
            self._high_lev_losses = 0

    def get_consecutive_wins(self) -> int:
        """Count consecutive wins from most recent."""
        count = 0
        for outcome in reversed(self._recent_outcomes):
            if outcome:
                count += 1
            else:
                break
        return count

    def get_consecutive_losses(self) -> int:
        """Count consecutive losses from most recent."""
        count = 0
        for outcome in reversed(self._recent_outcomes):
            if not outcome:
                count += 1
            else:
                break
        return count

    # ── Private helpers ───────────────────────────────────────────────

    def _get_streak_modifier(self) -> tuple:
        """Return (multiplier, description) based on win/loss streak."""
        wins = self.get_consecutive_wins()
        losses = self.get_consecutive_losses()

        if wins >= 2:
            return (1.15, f"win_streak({wins})(+15%)")
        elif losses >= 2:
            return (0.70, f"loss_streak({losses})(-30%)")
        return (1.0, "")

    @staticmethod
    def _is_counter_trend(side: str, regime: str) -> bool:
        """Check if trade direction opposes the regime trend."""
        regime_lower = regime.lower() if regime else "unknown"

        bull_regimes = {"trending_bull", "trend"}
        bear_regimes = {"trending_bear"}

        if side == "BUY" and regime_lower in bear_regimes:
            return True
        if side == "SELL" and regime_lower in bull_regimes:
            return True
        return False

    def _log_sizing(
        self, symbol: str, side: str, equity: float,
        entry: float, result: ConvictionResult,
    ) -> None:
        """Log sizing decision to JSONL."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "equity": equity,
            "entry": entry,
            "leverage": result.leverage,
            "risk_pct": result.risk_pct,
            "risk_amount": result.risk_amount,
            "notional": result.position_notional,
            "margin": result.margin_required,
            "pnl_tp": result.pnl_if_tp,
            "pnl_sl": result.pnl_if_sl,
            "rr": result.rr_ratio,
            "confluences": result.confluence_count,
            "sources": result.confluence_sources,
            "tier": result.conviction_tier,
            "precision_mode": result.precision_mode,
            "modifiers": result.modifiers_applied,
        }
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[CONVICTION] Failed to log: {e}")


def size_from_entry_map_record(
    equity: float,
    record: Dict[str, Any],
    sizer: Optional[ConvictionSizer] = None,
    multi_tf_aligned: bool = False,
    regime: str = "unknown",
    utc_hour: Optional[int] = None,
) -> Optional[ConvictionResult]:
    """
    Convenience: size a trade directly from an entry_map.json record.

    Entry map records have fields: symbol, level, direction, sl, tp,
    confluences, confluence_sources, atr, rsi, confidence, etc.
    """
    if sizer is None:
        sizer = ConvictionSizer()

    return sizer.size(
        equity=equity,
        entry_price=record.get("level", 0),
        sl_price=record.get("sl", 0),
        tp_price=record.get("tp", 0),
        confluences=record.get("confluences", 1),
        confluence_sources=record.get("confluence_sources", []),
        symbol=record.get("symbol", ""),
        side=record.get("direction", "BUY"),
        multi_tf_aligned=multi_tf_aligned,
        regime=regime,
        atr=record.get("atr"),
        utc_hour=utc_hour,
    )
