"""
Manual Position Management Rules Engine.

Tells the user exactly when to move stops, take partials, and exit.
Optimized for high-leverage scalps on a $100 Hyperliquid account.

Phases:
  ENTRY     — First 15 min after entry. Watch for false breakouts.
  EARLY     — 0.3-1.0% in profit. Lock in breakeven SL.
  SCALP_TP  — Approaching 1.5R. Take 50% off, move SL to entry + 0.5R.
  SWING     — Past scalp TP, holding for 3R. Trail SL progressively.
  EMERGENCY — Hard override rules (max loss, funding, time stop).

Each phase returns a concrete action: HOLD, TIGHTEN_SL, TAKE_PARTIAL, CLOSE.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List

logger = logging.getLogger("bot.manual.position_rules")


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class Phase(str, Enum):
    ENTRY = "ENTRY"
    EARLY = "EARLY"
    SCALP_TP = "SCALP_TP"
    SWING = "SWING"
    CLOSED = "CLOSED"


class Action(str, Enum):
    HOLD = "HOLD"
    TIGHTEN_SL = "TIGHTEN_SL"
    TAKE_PARTIAL = "TAKE_PARTIAL"
    CLOSE = "CLOSE"


# Fees: Hyperliquid taker ~0.035%, maker ~0.01%. Use taker as conservative.
HL_TAKER_FEE_PCT = 0.00035  # 0.035%
# Two legs (open + close) = ~0.07% round-trip
ROUND_TRIP_FEE_PCT = 2 * HL_TAKER_FEE_PCT


# ---------------------------------------------------------------------------
# Tier-specific rule parameters
# ---------------------------------------------------------------------------

# Rule params keyed by (tier, leverage_bucket).
# leverage_bucket: "high" = >20x, "medium" = 10-20x, "low" = <10x

@dataclass
class RuleParams:
    """All thresholds for one tier/leverage combo."""
    # Entry phase
    false_breakout_pct: float = 0.005       # 0.5% reversal in first 5 min = exit
    false_breakout_window_min: float = 5.0  # minutes to watch
    breakeven_trigger_pct: float = 0.003    # 0.3% in favor = move SL to BE

    # Early profit phase
    early_profit_min_pct: float = 0.003     # 0.3%
    early_profit_max_pct: float = 0.010     # 1.0%
    reversal_candle_count: int = 3          # 3 candles against = suggest close

    # Scalp TP phase
    scalp_tp_r: float = 1.5                 # take partial at 1.5R
    partial_close_pct: float = 0.50         # close 50% at scalp TP
    post_partial_sl_r: float = 0.5          # SL at entry + 0.5R after partial

    # Swing phase
    swing_trail_start_r: float = 1.0        # trail starts at 1R from entry
    swing_trail_2r: float = 1.5             # at 2R profit, trail at 1.5R
    swing_trail_3r: float = 2.5             # at 3R profit, trail at 2.5R
    time_stop_no_new_high_min: float = 120  # 2 hours no new high = close

    # Emergency rules
    emergency_loss_pct: float = 0.005       # 0.5% loss at high lev = close now
    emergency_funding_rate: float = 0.0005  # 0.05% funding against = factor in
    max_hold_hours: float = 12.0            # absolute max hold time


# Pre-built param sets
_SNIPER_HIGH_LEV = RuleParams(
    false_breakout_pct=0.004,       # tighter: 0.4% reversal = bail
    breakeven_trigger_pct=0.002,    # faster BE: 0.2% in favor
    scalp_tp_r=1.5,
    partial_close_pct=0.50,
    post_partial_sl_r=0.5,
    swing_trail_start_r=1.0,
    emergency_loss_pct=0.004,       # tighter: 0.4% loss = bail at 25x
    max_hold_hours=8.0,             # shorter max hold at high leverage
)

_SNIPER_MED_LEV = RuleParams(
    false_breakout_pct=0.005,
    breakeven_trigger_pct=0.003,
    scalp_tp_r=1.5,
    partial_close_pct=0.50,
    post_partial_sl_r=0.5,
    swing_trail_start_r=1.0,
    emergency_loss_pct=0.005,
    max_hold_hours=10.0,
)

_PREMIUM_HIGH_LEV = RuleParams(
    false_breakout_pct=0.005,
    breakeven_trigger_pct=0.003,
    scalp_tp_r=1.5,
    partial_close_pct=0.50,
    post_partial_sl_r=0.5,
    swing_trail_start_r=1.0,
    emergency_loss_pct=0.005,
    max_hold_hours=10.0,
)

_PREMIUM_MED_LEV = RuleParams(
    false_breakout_pct=0.006,
    breakeven_trigger_pct=0.003,
    scalp_tp_r=1.5,
    partial_close_pct=0.50,
    post_partial_sl_r=0.5,
    swing_trail_start_r=1.0,
    emergency_loss_pct=0.006,
    max_hold_hours=12.0,
)

_DEFAULT_PARAMS = RuleParams()


def _get_lev_bucket(leverage: float) -> str:
    if leverage > 20:
        return "high"
    if leverage >= 10:
        return "medium"
    return "low"


def _select_params(tier: str, leverage: float) -> RuleParams:
    bucket = _get_lev_bucket(leverage)
    key = (tier.upper(), bucket)
    table = {
        ("SNIPER", "high"): _SNIPER_HIGH_LEV,
        ("SNIPER", "medium"): _SNIPER_MED_LEV,
        ("SNIPER", "low"): _SNIPER_MED_LEV,
        ("PREMIUM", "high"): _PREMIUM_HIGH_LEV,
        ("PREMIUM", "medium"): _PREMIUM_MED_LEV,
        ("PREMIUM", "low"): _PREMIUM_MED_LEV,
    }
    return table.get(key, _DEFAULT_PARAMS)


# ---------------------------------------------------------------------------
# Position update result
# ---------------------------------------------------------------------------

@dataclass
class PositionUpdate:
    """Result from evaluating current position state."""
    phase: Phase
    action: Action
    reason: str
    # Suggested levels
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    # P&L
    pnl_pct: float = 0.0
    pnl_usd: float = 0.0
    pnl_r: float = 0.0
    # Timing
    hold_minutes: float = 0.0
    # Extra
    partial_close_pct: float = 0.0   # 0 = no partial, 0.5 = close 50%
    is_emergency: bool = False


# ---------------------------------------------------------------------------
# ManualPositionManager
# ---------------------------------------------------------------------------

class ManualPositionManager:
    """
    Rules engine for managing manual high-leverage positions.

    Usage:
        mgr = ManualPositionManager()
        update = mgr.evaluate(
            symbol="HYPE", side="BUY", entry=25.0, sl=24.50, tp_scalp=25.75,
            tp_swing=26.50, leverage=25, tier="SNIPER", current_price=25.30,
            entry_time=datetime(...), equity=100.0,
        )
        print(update.action, update.reason)
    """

    def evaluate(
        self,
        symbol: str,
        side: str,
        entry: float,
        sl: float,
        tp_scalp: float,
        tp_swing: float,
        leverage: float,
        tier: str,
        current_price: float,
        entry_time: datetime,
        equity: float = 100.0,
        position_size_usd: float = 0.0,
        partial_taken: bool = False,
        highest_price_since_entry: Optional[float] = None,
        last_new_high_time: Optional[datetime] = None,
        funding_rate: float = 0.0,
        recent_5m_candles: Optional[List[Dict[str, float]]] = None,
    ) -> PositionUpdate:
        """
        Evaluate current position and return management advice.

        Args:
            symbol: Trading pair (e.g. "HYPE")
            side: "BUY" or "SELL"
            entry: Entry price
            sl: Current stop loss
            tp_scalp: Scalp take-profit (1.5R)
            tp_swing: Swing take-profit (3R)
            leverage: Position leverage
            tier: Signal tier ("SNIPER" / "PREMIUM" / "STANDARD")
            current_price: Current market price
            entry_time: When position was opened (UTC)
            equity: Account equity in USD
            position_size_usd: Notional position size (for P&L calc)
            partial_taken: Whether 50% partial was already taken
            highest_price_since_entry: Best price since entry (for trailing)
            last_new_high_time: When the last new high occurred (for time stop)
            funding_rate: Current funding rate (positive = longs pay shorts)
            recent_5m_candles: Last N 5-minute candles [{open, high, low, close}]

        Returns:
            PositionUpdate with phase, action, reason, and suggested levels.
        """
        params = _select_params(tier, leverage)
        now = datetime.now(timezone.utc)
        hold_minutes = (now - entry_time).total_seconds() / 60.0

        # Directional helpers
        is_long = side.upper() == "BUY"
        risk = abs(entry - sl)
        if risk <= 0:
            return PositionUpdate(
                phase=Phase.CLOSED, action=Action.CLOSE,
                reason="Invalid position: zero risk width",
                hold_minutes=hold_minutes,
            )

        # Price movement from entry
        if is_long:
            move_pct = (current_price - entry) / entry
            move_r = (current_price - entry) / risk
        else:
            move_pct = (entry - current_price) / entry
            move_r = (entry - current_price) / risk

        # P&L in USD
        if position_size_usd > 0:
            pnl_usd = position_size_usd * move_pct
        else:
            pnl_usd = equity * (move_pct * leverage)

        pnl_pct = move_pct * leverage  # leveraged P&L %

        # Best price tracking
        if highest_price_since_entry is None:
            highest_price_since_entry = current_price
        if last_new_high_time is None:
            last_new_high_time = entry_time

        # ── EMERGENCY CHECKS (always first) ──
        emergency = self._check_emergency(
            params, is_long, move_pct, pnl_pct, leverage, hold_minutes,
            funding_rate, pnl_usd, equity, current_price, entry, sl, risk,
        )
        if emergency is not None:
            emergency.pnl_pct = pnl_pct
            emergency.pnl_usd = round(pnl_usd, 2)
            emergency.pnl_r = round(move_r, 2)
            emergency.hold_minutes = hold_minutes
            return emergency

        # ── PHASE DETECTION ──
        # Already took partial? We're in swing phase.
        if partial_taken:
            phase = Phase.SWING
        elif move_r >= params.scalp_tp_r * 0.9:
            # Close to or past scalp TP
            phase = Phase.SCALP_TP
        elif move_pct >= params.early_profit_min_pct:
            phase = Phase.EARLY
        elif hold_minutes <= 15:
            phase = Phase.ENTRY
        else:
            # Past 15 min but not yet profitable enough for EARLY
            # Still in entry-ish zone
            phase = Phase.ENTRY if move_pct < 0 else Phase.EARLY

        # ── DISPATCH TO PHASE HANDLER ──
        if phase == Phase.ENTRY:
            update = self._phase_entry(
                params, is_long, entry, sl, risk, current_price,
                move_pct, move_r, hold_minutes, recent_5m_candles,
            )
        elif phase == Phase.EARLY:
            update = self._phase_early(
                params, is_long, entry, sl, risk, current_price,
                move_pct, move_r, hold_minutes, recent_5m_candles,
            )
        elif phase == Phase.SCALP_TP:
            update = self._phase_scalp_tp(
                params, is_long, entry, sl, risk, current_price,
                move_pct, move_r, tp_scalp, partial_taken,
            )
        elif phase == Phase.SWING:
            update = self._phase_swing(
                params, is_long, entry, sl, risk, current_price,
                move_pct, move_r, tp_swing, highest_price_since_entry,
                last_new_high_time, hold_minutes,
            )
        else:
            update = PositionUpdate(
                phase=Phase.ENTRY, action=Action.HOLD,
                reason="Position open, monitoring.",
            )

        update.pnl_pct = round(pnl_pct, 4)
        update.pnl_usd = round(pnl_usd, 2)
        update.pnl_r = round(move_r, 2)
        update.hold_minutes = round(hold_minutes, 1)
        return update

    # ------------------------------------------------------------------
    # Phase handlers
    # ------------------------------------------------------------------

    def _phase_entry(
        self, params: RuleParams, is_long: bool, entry: float, sl: float,
        risk: float, price: float, move_pct: float, move_r: float,
        hold_minutes: float, candles: Optional[List[Dict]] = None,
    ) -> PositionUpdate:
        """ENTRY phase: first 15 min. Watch for false breakouts."""

        # False breakout detection: reversal > threshold in first 5 min
        if hold_minutes <= params.false_breakout_window_min:
            if move_pct < -params.false_breakout_pct:
                loss_pct_display = abs(move_pct) * 100
                return PositionUpdate(
                    phase=Phase.ENTRY, action=Action.CLOSE,
                    reason=(
                        f"FALSE BREAKOUT: Price reversed {loss_pct_display:.1f}% "
                        f"against us in first {hold_minutes:.0f} min. "
                        f"Close now for small loss instead of waiting for full SL."
                    ),
                    suggested_sl=price,  # close at market
                )

        # Quick profit: move SL to breakeven (minus fees)
        if move_pct >= params.breakeven_trigger_pct:
            fee_buffer = entry * ROUND_TRIP_FEE_PCT
            if is_long:
                be_sl = entry + fee_buffer
            else:
                be_sl = entry - fee_buffer

            return PositionUpdate(
                phase=Phase.ENTRY, action=Action.TIGHTEN_SL,
                reason=(
                    f"Quick move in our favor (+{move_pct*100:.1f}%). "
                    f"Move SL to breakeven at {be_sl:.4f} (entry + fees)."
                ),
                suggested_sl=round(be_sl, 6),
            )

        # Check candle momentum (if candles provided)
        if candles and len(candles) >= 3:
            bearish = self._count_against_candles(candles[-3:], is_long)
            if bearish >= 3 and move_pct < 0:
                return PositionUpdate(
                    phase=Phase.ENTRY, action=Action.CLOSE,
                    reason=(
                        f"3 consecutive 5m candles against us and position "
                        f"is underwater ({move_pct*100:.2f}%). Consider closing."
                    ),
                    suggested_sl=price,
                )

        # Default: hold and watch
        return PositionUpdate(
            phase=Phase.ENTRY, action=Action.HOLD,
            reason=(
                f"Entry phase ({hold_minutes:.0f} min). "
                f"Watching for breakout confirmation. "
                f"SL at {sl:.4f}, target BE move at +{params.breakeven_trigger_pct*100:.1f}%."
            ),
            suggested_sl=sl,
        )

    def _phase_early(
        self, params: RuleParams, is_long: bool, entry: float, sl: float,
        risk: float, price: float, move_pct: float, move_r: float,
        hold_minutes: float, candles: Optional[List[Dict]] = None,
    ) -> PositionUpdate:
        """EARLY PROFIT phase: 0.3-1.0% in profit. Lock breakeven."""

        # SL should be at breakeven now
        fee_buffer = entry * ROUND_TRIP_FEE_PCT
        if is_long:
            be_sl = entry + fee_buffer
            sl_needs_update = sl < be_sl
        else:
            be_sl = entry - fee_buffer
            sl_needs_update = sl > be_sl

        if sl_needs_update:
            return PositionUpdate(
                phase=Phase.EARLY, action=Action.TIGHTEN_SL,
                reason=(
                    f"Profit +{move_pct*100:.1f}% — move SL to breakeven "
                    f"at {be_sl:.4f}. Risk-free trade now."
                ),
                suggested_sl=round(be_sl, 6),
            )

        # Watch for reversal candles
        if candles and len(candles) >= 3:
            bearish = self._count_against_candles(candles[-3:], is_long)
            if bearish >= 3:
                return PositionUpdate(
                    phase=Phase.EARLY, action=Action.CLOSE,
                    reason=(
                        f"3 consecutive 5m candles against us at +{move_pct*100:.1f}%. "
                        f"Lock in profit now before reversal completes."
                    ),
                    suggested_sl=price,
                )

        # Approaching scalp TP?
        if move_r >= params.scalp_tp_r * 0.8:
            return PositionUpdate(
                phase=Phase.EARLY, action=Action.HOLD,
                reason=(
                    f"Approaching scalp TP ({move_r:.1f}R / {params.scalp_tp_r}R). "
                    f"Prepare to take 50% off. SL locked at BE."
                ),
                suggested_sl=round(be_sl, 6),
            )

        return PositionUpdate(
            phase=Phase.EARLY, action=Action.HOLD,
            reason=(
                f"Early profit +{move_pct*100:.1f}% ({move_r:.1f}R). "
                f"SL at breakeven. Holding for scalp TP at {params.scalp_tp_r}R."
            ),
            suggested_sl=round(be_sl, 6),
        )

    def _phase_scalp_tp(
        self, params: RuleParams, is_long: bool, entry: float, sl: float,
        risk: float, price: float, move_pct: float, move_r: float,
        tp_scalp: float, partial_taken: bool,
    ) -> PositionUpdate:
        """SCALP TP phase: at or near 1.5R. Take 50% partial."""

        if not partial_taken:
            # Calculate post-partial SL (entry + 0.5R)
            if is_long:
                new_sl = entry + risk * params.post_partial_sl_r
            else:
                new_sl = entry - risk * params.post_partial_sl_r

            return PositionUpdate(
                phase=Phase.SCALP_TP, action=Action.TAKE_PARTIAL,
                reason=(
                    f"SCALP TP zone reached ({move_r:.1f}R / +{move_pct*100:.1f}%). "
                    f"Take {params.partial_close_pct*100:.0f}% off now. "
                    f"Move SL to {new_sl:.4f} (entry + {params.post_partial_sl_r}R) "
                    f"for remaining position."
                ),
                suggested_sl=round(new_sl, 6),
                suggested_tp=tp_scalp,
                partial_close_pct=params.partial_close_pct,
            )

        # Partial already taken — transition to swing logic
        if is_long:
            trail_sl = entry + risk * params.swing_trail_start_r
        else:
            trail_sl = entry - risk * params.swing_trail_start_r

        return PositionUpdate(
            phase=Phase.SCALP_TP, action=Action.TIGHTEN_SL,
            reason=(
                f"Partial taken. Remaining 50% targeting swing TP. "
                f"Trail SL at {trail_sl:.4f} (entry + {params.swing_trail_start_r}R)."
            ),
            suggested_sl=round(trail_sl, 6),
        )

    def _phase_swing(
        self, params: RuleParams, is_long: bool, entry: float, sl: float,
        risk: float, price: float, move_pct: float, move_r: float,
        tp_swing: float, highest_price: float, last_new_high_time: datetime,
        hold_minutes: float,
    ) -> PositionUpdate:
        """SWING phase: past scalp TP, trailing toward 3R."""

        now = datetime.now(timezone.utc)

        # Progressive trailing stop
        if move_r >= 3.0:
            trail_r = params.swing_trail_3r  # 2.5R
        elif move_r >= 2.0:
            trail_r = params.swing_trail_2r  # 1.5R
        else:
            trail_r = params.swing_trail_start_r  # 1.0R

        if is_long:
            trail_sl = entry + risk * trail_r
            # Never move SL backward
            trail_sl = max(trail_sl, sl)
        else:
            trail_sl = entry - risk * trail_r
            trail_sl = min(trail_sl, sl)

        # Time stop: no new high in 2 hours
        minutes_since_high = (now - last_new_high_time).total_seconds() / 60.0
        if minutes_since_high >= params.time_stop_no_new_high_min:
            return PositionUpdate(
                phase=Phase.SWING, action=Action.CLOSE,
                reason=(
                    f"TIME STOP: No new high in {minutes_since_high:.0f} min "
                    f"({params.time_stop_no_new_high_min:.0f} min limit). "
                    f"Momentum exhausted. Close at market for +{move_pct*100:.1f}%."
                ),
                suggested_sl=price,
            )

        # At swing TP target?
        if is_long:
            at_swing_tp = price >= tp_swing
        else:
            at_swing_tp = price <= tp_swing

        if at_swing_tp:
            return PositionUpdate(
                phase=Phase.SWING, action=Action.CLOSE,
                reason=(
                    f"SWING TP HIT at {move_r:.1f}R (+{move_pct*100:.1f}%). "
                    f"Close remaining position. Full target achieved."
                ),
                suggested_sl=price,
            )

        # SL needs tightening?
        if is_long:
            needs_tighten = trail_sl > sl
        else:
            needs_tighten = trail_sl < sl

        if needs_tighten:
            return PositionUpdate(
                phase=Phase.SWING, action=Action.TIGHTEN_SL,
                reason=(
                    f"Swing phase at {move_r:.1f}R. Tighten SL to {trail_sl:.4f} "
                    f"(locking {trail_r:.1f}R profit). Target: {tp_swing:.4f}."
                ),
                suggested_sl=round(trail_sl, 6),
            )

        return PositionUpdate(
            phase=Phase.SWING, action=Action.HOLD,
            reason=(
                f"Swing phase at {move_r:.1f}R (+{move_pct*100:.1f}%). "
                f"Trailing SL at {sl:.4f} ({trail_r:.1f}R locked). "
                f"Target: {tp_swing:.4f} ({hold_minutes/60:.1f}h held)."
            ),
            suggested_sl=round(trail_sl, 6),
        )

    # ------------------------------------------------------------------
    # Emergency checks
    # ------------------------------------------------------------------

    def _check_emergency(
        self, params: RuleParams, is_long: bool, move_pct: float,
        pnl_pct: float, leverage: float, hold_minutes: float,
        funding_rate: float, pnl_usd: float, equity: float,
        price: float, entry: float, sl: float, risk: float,
    ) -> Optional[PositionUpdate]:
        """Check emergency exit rules. Returns PositionUpdate if triggered."""

        # Rule 1: High leverage + loss exceeds threshold → close immediately
        if leverage > 20 and move_pct < -params.emergency_loss_pct:
            return PositionUpdate(
                phase=Phase.ENTRY, action=Action.CLOSE,
                reason=(
                    f"EMERGENCY: {leverage:.0f}x leverage with "
                    f"{abs(move_pct)*100:.1f}% adverse move "
                    f"(= {abs(pnl_pct)*100:.0f}% account loss). "
                    f"Close NOW. Don't wait for SL."
                ),
                suggested_sl=price,
                is_emergency=True,
            )

        # Rule 2: Funding rate strongly against position
        if funding_rate != 0:
            # Positive funding = longs pay shorts
            funding_against = (funding_rate > params.emergency_funding_rate and is_long) or \
                              (funding_rate < -params.emergency_funding_rate and not is_long)
            if funding_against and move_pct < 0:
                hourly_cost_pct = abs(funding_rate) * leverage
                return PositionUpdate(
                    phase=Phase.ENTRY, action=Action.CLOSE,
                    reason=(
                        f"EMERGENCY: Funding rate {funding_rate*100:.3f}% "
                        f"against your {'long' if is_long else 'short'} "
                        f"(costing ~{hourly_cost_pct*100:.1f}%/8h at {leverage:.0f}x). "
                        f"Position already underwater. Close to stop bleeding."
                    ),
                    suggested_sl=price,
                    is_emergency=True,
                )

        # Rule 3: Max hold time exceeded
        if hold_minutes >= params.max_hold_hours * 60:
            return PositionUpdate(
                phase=Phase.SWING if move_pct > 0 else Phase.ENTRY,
                action=Action.CLOSE,
                reason=(
                    f"TIME LIMIT: Position held {hold_minutes/60:.1f}h "
                    f"(max {params.max_hold_hours:.0f}h for {leverage:.0f}x leverage). "
                    f"Overnight risk at high leverage is not worth it. Close at market."
                ),
                suggested_sl=price,
                is_emergency=True,
            )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_against_candles(candles: List[Dict[str, float]], is_long: bool) -> int:
        """Count consecutive candles going against position direction."""
        count = 0
        for c in candles:
            close = c.get("close", 0)
            open_ = c.get("open", 0)
            if is_long and close < open_:
                count += 1
            elif not is_long and close > open_:
                count += 1
            else:
                count = 0  # reset on a candle in our favor
        return count


# ---------------------------------------------------------------------------
# Public API: format_position_update
# ---------------------------------------------------------------------------

def format_position_update(
    symbol: str,
    side: str,
    entry: float,
    current_price: float,
    leverage: float,
    tier: str,
    equity: float,
    sl: float,
    tp_scalp: float,
    tp_swing: float,
    entry_time: datetime,
    position_size_usd: float = 0.0,
    partial_taken: bool = False,
    highest_price: Optional[float] = None,
    last_new_high_time: Optional[datetime] = None,
    funding_rate: float = 0.0,
    recent_5m_candles: Optional[List[Dict[str, float]]] = None,
) -> str:
    """
    Returns a Telegram-ready message with position management advice.

    Call this with current market data and it tells you exactly what to do.
    """
    mgr = ManualPositionManager()
    update = mgr.evaluate(
        symbol=symbol, side=side, entry=entry, sl=sl,
        tp_scalp=tp_scalp, tp_swing=tp_swing, leverage=leverage,
        tier=tier, current_price=current_price, entry_time=entry_time,
        equity=equity, position_size_usd=position_size_usd,
        partial_taken=partial_taken,
        highest_price_since_entry=highest_price,
        last_new_high_time=last_new_high_time,
        funding_rate=funding_rate,
        recent_5m_candles=recent_5m_candles,
    )

    # Action emoji mapping
    action_icons = {
        Action.HOLD: "HOLD",
        Action.TIGHTEN_SL: "TIGHTEN SL",
        Action.TAKE_PARTIAL: "TAKE PARTIAL",
        Action.CLOSE: "CLOSE NOW",
    }

    pnl_sign = "+" if update.pnl_usd >= 0 else ""
    pnl_pct_display = update.pnl_pct * 100  # already leveraged

    lines = [
        f"{'='*30}",
        f"  POSITION: {symbol} {side} {leverage:.0f}x [{tier}]",
        f"{'='*30}",
        f"",
        f"Phase: {update.phase.value}",
        f"P&L: {pnl_sign}${update.pnl_usd:.2f} ({pnl_sign}{pnl_pct_display:.1f}%) [{update.pnl_r:.1f}R]",
        f"Hold: {update.hold_minutes:.0f} min",
        f"",
        f">>> {action_icons.get(update.action, update.action.value)} <<<",
        f"",
        f"{update.reason}",
        f"",
    ]

    if update.suggested_sl is not None:
        lines.append(f"SL: {update.suggested_sl:.4f}")
    if update.suggested_tp is not None:
        lines.append(f"TP: {update.suggested_tp:.4f}")
    if update.partial_close_pct > 0:
        lines.append(f"Close: {update.partial_close_pct*100:.0f}% of position")
    if update.is_emergency:
        lines.append(f"")
        lines.append(f"*** EMERGENCY EXIT — ACT NOW ***")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API: get_management_rules
# ---------------------------------------------------------------------------

def get_management_rules(tier: str, leverage: float, hold_time_minutes: float) -> Dict[str, Any]:
    """
    Returns the applicable rules for the current position state.

    Different rules for SNIPER (25x) vs PREMIUM (15x) — tighter at higher leverage.
    """
    params = _select_params(tier, leverage)

    # Determine current phase based on hold time
    if hold_time_minutes <= 15:
        current_phase = "ENTRY"
        phase_rules = {
            "false_breakout_threshold": f"{params.false_breakout_pct*100:.1f}%",
            "false_breakout_window": f"{params.false_breakout_window_min:.0f} min",
            "breakeven_trigger": f"+{params.breakeven_trigger_pct*100:.1f}% in favor",
            "action_if_reversal": "Close at market for small loss",
            "action_if_favorable": "Move SL to breakeven (entry + fees)",
        }
    elif hold_time_minutes <= 60:
        current_phase = "EARLY_PROFIT"
        phase_rules = {
            "sl_target": "Breakeven (entry + round-trip fees)",
            "watch_for": "3 consecutive bearish 5m candles",
            "action_if_reversal": "Close at current profit",
            "next_target": f"Scalp TP at {params.scalp_tp_r}R",
        }
    elif hold_time_minutes <= 180:
        current_phase = "SCALP_TP"
        phase_rules = {
            "partial_close": f"{params.partial_close_pct*100:.0f}%",
            "scalp_tp_target": f"{params.scalp_tp_r}R",
            "post_partial_sl": f"Entry + {params.post_partial_sl_r}R",
            "remaining": f"{(1-params.partial_close_pct)*100:.0f}% trails toward swing TP",
        }
    else:
        current_phase = "SWING"
        phase_rules = {
            "trailing_at_1r": f"SL at entry + {params.swing_trail_start_r}R",
            "trailing_at_2r": f"SL at entry + {params.swing_trail_2r}R",
            "trailing_at_3r": f"SL at entry + {params.swing_trail_3r}R",
            "time_stop": f"Close if no new high in {params.time_stop_no_new_high_min:.0f} min",
        }

    return {
        "tier": tier,
        "leverage": leverage,
        "leverage_bucket": _get_lev_bucket(leverage),
        "hold_time_minutes": hold_time_minutes,
        "current_phase": current_phase,
        "phase_rules": phase_rules,
        "emergency_rules": {
            "max_loss_before_emergency": f"{params.emergency_loss_pct*100:.1f}% (at >{20}x lev)",
            "max_funding_rate": f"{params.emergency_funding_rate*100:.3f}%",
            "max_hold_hours": params.max_hold_hours,
        },
        "general": {
            "round_trip_fees": f"{ROUND_TRIP_FEE_PCT*100:.3f}%",
            "partial_close_at": f"{params.scalp_tp_r}R",
            "partial_size": f"{params.partial_close_pct*100:.0f}%",
        },
    }
