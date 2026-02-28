"""
Trade Rotation & Re-evaluation Manager.

Evaluates whether an open position should be rotated into a better signal.
Prevents getting stuck in stale trades and captures better R/R opportunities.

Rotation rules:
1. PROFIT ROTATION: If current trade is in profit and a new signal has
   significantly better R/R, rotate to the new signal.
2. LOSS AVOIDANCE ROTATION: If current trade is losing and a new signal
   on a different symbol has much stronger conviction, rotate to cut
   losses early and catch a better move.

Anti-spam protections (fee awareness):
- Minimum time between rotations per symbol (cooldown)
- Minimum R/R improvement threshold to justify fees
- Maximum rotations per rolling window
- New signal must clear a higher confidence bar than normal entries

Flow:
1. Each tick, evaluate_rotations() is called with current open positions
   and any new candidate signals.
2. For each open position, compare its current state against candidates.
3. If a candidate passes the rotation threshold, return a RotationAction.
4. Caller (loop_once) executes: close old position, open new one.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("bot.execution.rotation")


@dataclass
class RotationAction:
    """A recommended rotation: close existing, open new."""
    close_symbol: str
    close_side: str
    close_reason: str        # "ROTATE_PROFIT" or "ROTATE_LOSS_AVOIDANCE"
    open_signal: Dict[str, Any]  # new signal dict (symbol, side, entry, sl, tp1, tp2)
    current_unrealized_pnl: float
    current_unrealized_pct: float
    new_rr_ratio: float      # R/R of the new signal
    old_rr_ratio: float      # remaining R/R of the old position
    rr_improvement: float    # how much better the new signal is
    confidence_new: float    # confidence of the new signal
    timestamp: float = field(default_factory=time.time)


@dataclass
class RotationConfig:
    """Configuration for rotation behavior. Conservative defaults."""

    # ── Cooldowns ──
    # Minimum seconds after opening before a position can be rotated
    min_hold_before_rotation_s: int = 300  # 5 minutes minimum hold

    # Minimum seconds between any two rotations (global)
    global_rotation_cooldown_s: int = 600  # 10 minutes between rotations

    # Per-symbol cooldown: can't rotate back into a symbol we just left
    symbol_rotation_cooldown_s: int = 1800  # 30 minutes before re-entering same symbol

    # ── Rate limits ──
    # Max rotations in a rolling window
    max_rotations_per_hour: int = 2
    max_rotations_per_day: int = 6

    # ── Profit rotation thresholds ──
    # Minimum unrealized profit % before we consider rotating (for profit rotations)
    min_profit_pct_to_rotate: float = 0.3  # 0.3% profit minimum

    # New signal must have R/R at least this much better than remaining R/R
    min_rr_improvement_profit: float = 1.5  # new R/R must be 1.5x better

    # Minimum confidence for the new signal (higher bar than normal entry)
    min_confidence_for_rotation: float = 75.0  # 75% vs normal 60% entry threshold

    # ── Loss avoidance thresholds ──
    # Maximum unrealized loss % before we consider loss-avoidance rotation
    max_loss_pct_for_rotation: float = -2.0  # only rotate if losing less than 2%

    # For loss rotations, new signal needs even stronger conviction
    min_rr_improvement_loss: float = 2.0  # new R/R must be 2x better

    # Minimum confidence for loss-avoidance rotation (highest bar)
    min_confidence_for_loss_rotation: float = 80.0

    # ── Fee awareness ──
    # Estimated round-trip fee cost in % (entry + exit = 2 * taker fee)
    estimated_round_trip_fee_pct: float = 0.10  # 10 bps total

    # New signal's expected profit must exceed fees by this multiple
    min_profit_to_fee_ratio: float = 3.0  # expected profit must be 3x fees


class RotationManager:
    """
    Manages trade rotation decisions with anti-spam protection.

    Tracks rotation history to enforce cooldowns and rate limits.
    Evaluates candidate signals against open positions for rotation.
    """

    def __init__(self, config: Optional[RotationConfig] = None):
        self.config = config or RotationConfig()
        self._rotation_history: List[Dict[str, Any]] = []
        self._last_rotation_time: float = 0.0
        # Track when we last left each symbol (for re-entry cooldown)
        self._symbol_exit_times: Dict[str, float] = {}

    def evaluate_rotations(
        self,
        open_positions: Dict[str, Dict[str, Any]],
        candidate_signals: List[Dict[str, Any]],
        current_prices: Dict[str, float],
    ) -> List[RotationAction]:
        """
        Evaluate whether any open position should be rotated.

        Args:
            open_positions: {symbol: position_dict} of currently open positions
            candidate_signals: list of new signal dicts that passed filters
            current_prices: {symbol: latest_price} for PnL calculation

        Returns:
            List of RotationAction recommendations (usually 0 or 1).
        """
        if not open_positions or not candidate_signals:
            return []

        # Global cooldown check
        now = time.time()
        if now - self._last_rotation_time < self.config.global_rotation_cooldown_s:
            return []

        # Rate limit check
        if not self._check_rate_limits(now):
            return []

        actions = []

        for symbol, pos in open_positions.items():
            if not isinstance(pos, dict) or pos.get("status") != "open":
                continue

            price = current_prices.get(symbol)
            if price is None:
                continue

            # Check minimum hold time
            open_time = pos.get("open_time")
            if open_time:
                if isinstance(open_time, str):
                    try:
                        open_dt = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                        hold_s = (datetime.now(timezone.utc) - open_dt).total_seconds()
                    except (ValueError, TypeError):
                        hold_s = 0
                else:
                    hold_s = 0
            else:
                hold_s = 0

            if hold_s < self.config.min_hold_before_rotation_s:
                continue

            # Compute current position metrics
            entry = pos["entry"]
            side = pos["side"]
            sl = pos["sl"]
            tp2 = pos.get("tp2", pos.get("tp1", entry))

            unrealized_pnl, unrealized_pct = self._compute_unrealized(
                entry, price, side, pos.get("qty", 1.0)
            )
            old_rr = self._compute_remaining_rr(entry, price, sl, tp2, side)

            # Evaluate each candidate as a potential rotation target
            for candidate in candidate_signals:
                cand_symbol = candidate["symbol"]

                # Don't rotate into the same position
                if cand_symbol == symbol and candidate["side"] == side:
                    continue

                # Check symbol re-entry cooldown
                if cand_symbol in self._symbol_exit_times:
                    time_since_exit = now - self._symbol_exit_times[cand_symbol]
                    if time_since_exit < self.config.symbol_rotation_cooldown_s:
                        continue

                # Compute new signal R/R
                new_rr = self._compute_signal_rr(candidate)
                if new_rr <= 0:
                    continue

                confidence = candidate.get("confidence", candidate.get("align_score", 0))
                # If align_score is out of 4, normalize to percentage
                if 0 < confidence <= 4:
                    confidence = confidence * 25.0

                # Check rotation viability
                action = self._evaluate_rotation(
                    pos_symbol=symbol,
                    pos_side=side,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pct=unrealized_pct,
                    old_rr=old_rr,
                    new_rr=new_rr,
                    candidate=candidate,
                    confidence=confidence,
                )

                if action is not None:
                    actions.append(action)

        # If multiple rotation options, pick the best one (highest R/R improvement)
        if len(actions) > 1:
            actions.sort(key=lambda a: a.rr_improvement, reverse=True)
            return [actions[0]]

        return actions

    def record_rotation(self, action: RotationAction):
        """Record that a rotation was executed (for cooldown/rate tracking)."""
        now = time.time()
        self._last_rotation_time = now
        self._symbol_exit_times[action.close_symbol] = now

        self._rotation_history.append({
            "timestamp": now,
            "from_symbol": action.close_symbol,
            "to_symbol": action.open_signal["symbol"],
            "reason": action.close_reason,
            "pnl_at_rotation": action.current_unrealized_pnl,
            "rr_improvement": action.rr_improvement,
        })

        logger.info(
            f"ROTATION recorded: {action.close_symbol} -> {action.open_signal['symbol']} "
            f"reason={action.close_reason} pnl={action.current_unrealized_pnl:.2f} "
            f"rr_improvement={action.rr_improvement:.2f}x"
        )

    def get_rotation_stats(self) -> Dict[str, Any]:
        """Return rotation statistics for monitoring."""
        now = time.time()
        hour_ago = now - 3600
        day_ago = now - 86400

        rotations_last_hour = sum(
            1 for r in self._rotation_history if r["timestamp"] > hour_ago
        )
        rotations_last_day = sum(
            1 for r in self._rotation_history if r["timestamp"] > day_ago
        )

        return {
            "total_rotations": len(self._rotation_history),
            "rotations_last_hour": rotations_last_hour,
            "rotations_last_day": rotations_last_day,
            "max_per_hour": self.config.max_rotations_per_hour,
            "max_per_day": self.config.max_rotations_per_day,
            "last_rotation_ago_s": int(now - self._last_rotation_time) if self._last_rotation_time > 0 else None,
            "cooldown_remaining_s": max(0, int(self.config.global_rotation_cooldown_s - (now - self._last_rotation_time))),
        }

    # ── Internal helpers ──

    def _check_rate_limits(self, now: float) -> bool:
        """Check if we're within rotation rate limits."""
        hour_ago = now - 3600
        day_ago = now - 86400

        rotations_last_hour = sum(
            1 for r in self._rotation_history if r["timestamp"] > hour_ago
        )
        if rotations_last_hour >= self.config.max_rotations_per_hour:
            logger.debug(
                f"Rotation rate limit: {rotations_last_hour}/{self.config.max_rotations_per_hour} per hour"
            )
            return False

        rotations_last_day = sum(
            1 for r in self._rotation_history if r["timestamp"] > day_ago
        )
        if rotations_last_day >= self.config.max_rotations_per_day:
            logger.debug(
                f"Rotation rate limit: {rotations_last_day}/{self.config.max_rotations_per_day} per day"
            )
            return False

        return True

    def _compute_unrealized(
        self, entry: float, price: float, side: str, qty: float
    ) -> Tuple[float, float]:
        """Compute unrealized PnL in USD and as a percentage."""
        if side == "BUY":
            pnl = (price - entry) * qty
        else:
            pnl = (entry - price) * qty

        pct = ((price - entry) / entry * 100) if side == "BUY" else ((entry - price) / entry * 100)
        return pnl, pct

    def _compute_remaining_rr(
        self, entry: float, current_price: float, sl: float, tp2: float, side: str
    ) -> float:
        """
        Compute remaining R/R ratio from current price to target vs current price to SL.
        Uses current price (not entry) since that's our actual risk/reward from here.
        """
        if side == "BUY":
            remaining_reward = tp2 - current_price
            remaining_risk = current_price - sl
        else:
            remaining_reward = current_price - tp2
            remaining_risk = sl - current_price

        if remaining_risk <= 0:
            return 0.0  # SL already breached or at entry

        return max(remaining_reward / remaining_risk, 0.0)

    def _compute_signal_rr(self, signal: Dict[str, Any]) -> float:
        """Compute R/R ratio for a new signal from its entry/SL/TP2."""
        entry = signal.get("entry", 0)
        sl = signal.get("sl", 0)
        tp2 = signal.get("tp2", signal.get("tp1", 0))
        side = signal.get("side", "BUY")

        if entry <= 0 or sl <= 0 or tp2 <= 0:
            return 0.0

        if side == "BUY":
            risk = entry - sl
            reward = tp2 - entry
        else:
            risk = sl - entry
            reward = entry - tp2

        if risk <= 0:
            return 0.0

        return reward / risk

    def _evaluate_rotation(
        self,
        pos_symbol: str,
        pos_side: str,
        unrealized_pnl: float,
        unrealized_pct: float,
        old_rr: float,
        new_rr: float,
        candidate: Dict[str, Any],
        confidence: float,
    ) -> Optional[RotationAction]:
        """
        Decide whether to rotate from an existing position to a candidate signal.
        Returns RotationAction if rotation is justified, None otherwise.
        """
        cfg = self.config

        # Fee check: new signal's expected profit must justify round-trip fees
        # (closing old + opening new = 2 round trips of fees)
        cand_entry = candidate["entry"]
        cand_sl = candidate["sl"]
        cand_tp1 = candidate.get("tp1", cand_entry)
        cand_side = candidate["side"]

        # Use TP1 as conservative expected profit target
        if cand_side == "BUY":
            expected_profit_pct = ((cand_tp1 - cand_entry) / cand_entry) * 100
        else:
            expected_profit_pct = ((cand_entry - cand_tp1) / cand_entry) * 100

        total_fee_pct = cfg.estimated_round_trip_fee_pct * 2  # close old + open new
        if expected_profit_pct <= 0 or expected_profit_pct / total_fee_pct < cfg.min_profit_to_fee_ratio:
            return None

        # ── PROFIT ROTATION ──
        if unrealized_pct >= cfg.min_profit_pct_to_rotate:
            # In profit: check if new signal is materially better
            if confidence < cfg.min_confidence_for_rotation:
                return None

            rr_improvement = new_rr / old_rr if old_rr > 0 else new_rr
            if rr_improvement < cfg.min_rr_improvement_profit:
                return None

            logger.info(
                f"ROTATION CANDIDATE (profit): {pos_symbol} -> {candidate['symbol']} | "
                f"current_pnl={unrealized_pct:+.2f}% | old_rr={old_rr:.2f} new_rr={new_rr:.2f} "
                f"improvement={rr_improvement:.2f}x | confidence={confidence:.0f}%"
            )

            return RotationAction(
                close_symbol=pos_symbol,
                close_side=pos_side,
                close_reason="ROTATE_PROFIT",
                open_signal=candidate,
                current_unrealized_pnl=unrealized_pnl,
                current_unrealized_pct=unrealized_pct,
                new_rr_ratio=new_rr,
                old_rr_ratio=old_rr,
                rr_improvement=rr_improvement,
                confidence_new=confidence,
            )

        # ── LOSS AVOIDANCE ROTATION ──
        if unrealized_pct < 0 and unrealized_pct >= cfg.max_loss_pct_for_rotation:
            # In a loss but not catastrophic: can we find something much better?
            if confidence < cfg.min_confidence_for_loss_rotation:
                return None

            rr_improvement = new_rr / old_rr if old_rr > 0 else new_rr
            if rr_improvement < cfg.min_rr_improvement_loss:
                return None

            logger.info(
                f"ROTATION CANDIDATE (loss avoidance): {pos_symbol} -> {candidate['symbol']} | "
                f"current_pnl={unrealized_pct:+.2f}% | old_rr={old_rr:.2f} new_rr={new_rr:.2f} "
                f"improvement={rr_improvement:.2f}x | confidence={confidence:.0f}%"
            )

            return RotationAction(
                close_symbol=pos_symbol,
                close_side=pos_side,
                close_reason="ROTATE_LOSS_AVOIDANCE",
                open_signal=candidate,
                current_unrealized_pnl=unrealized_pnl,
                current_unrealized_pct=unrealized_pct,
                new_rr_ratio=new_rr,
                old_rr_ratio=old_rr,
                rr_improvement=rr_improvement,
                confidence_new=confidence,
            )

        return None

    def cleanup_old_history(self, max_age_s: int = 86400 * 7):
        """Prune rotation history older than max_age_s (default 7 days)."""
        cutoff = time.time() - max_age_s
        self._rotation_history = [
            r for r in self._rotation_history if r["timestamp"] > cutoff
        ]
