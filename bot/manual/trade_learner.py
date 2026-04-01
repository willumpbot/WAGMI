"""
Post-Trade Learning System — Immediate adaptation after every trade close.

Principle: every trade teaches something. The system gets smarter after EVERY
close, not just accumulates data passively.

After each trade close:
  1. Classify the setup type (BB, EMA, S/R, VWAP, Fib, etc.)
  2. Diagnose WHY it won or lost (SL too tight, TP too far, bad entry, etc.)
  3. Compute R-multiple achieved
  4. Update per-setup-type performance stats
  5. Apply immediate parameter adjustments for the next trade
  6. Optionally trigger entry map regeneration after losses
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.manual.trade_learner")

# ── Paths ──────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join("data", "manual")
_LEARNER_PATH = os.path.join(_DATA_DIR, "trade_learner_state.json")
_LESSONS_PATH = os.path.join(_DATA_DIR, "trade_lessons.jsonl")

# ── Setup type classification ──────────────────────────────────────────
# Maps known source/setup_type labels from entry_map_generator and
# anticipatory_entries to canonical setup types.
SETUP_TYPE_MAP = {
    # entry_map_generator sources
    "BB_Lower": "bb_lower_bounce",
    "BB_Upper": "bb_upper_rejection",
    "BB_Mid": "bb_mid_reversion",
    "EMA9": "ema_pullback",
    "EMA20": "ema_pullback",
    "EMA50": "ema_pullback",
    "VWAP": "vwap_reversion",
    "Session_Low": "session_low_bounce",
    "Session_High": "session_high_rejection",
    "Swing_High": "resistance_rejection",
    "Swing_Low": "support_bounce",
    "Round_Number": "round_number",
    "Fib_236": "fib_retracement",
    "Fib_382": "fib_retracement",
    "Fib_500": "fib_retracement",
    "Fib_618": "fib_retracement",
    "Fib_786": "fib_retracement",
    # anticipatory_entries setup_types
    "bb_upper_rejection": "bb_upper_rejection",
    "bb_lower_bounce": "bb_lower_bounce",
    "resistance_rejection": "resistance_rejection",
    "support_bounce": "support_bounce",
    "ema20_bear_touch": "ema_pullback",
    "ema20_bull_touch": "ema_pullback",
    "vwap_rejection": "vwap_reversion",
    "vwap_bounce": "vwap_reversion",
}

# Default setup type when source is unknown
DEFAULT_SETUP_TYPE = "unknown_setup"

# ── Diagnosis thresholds ───────────────────────────────────────────────
# If SL was hit within this many seconds, entry was bad (price reversed immediately)
FAST_SL_THRESHOLD_S = 2 * 3600      # 2 hours (approx 2 bars on 1h)
# If SL hit after this many seconds of chop, setup was right but market wasn't ready
CHOP_SL_THRESHOLD_S = 5 * 3600      # 5 hours (approx 5 bars on 1h)

# ── Adjustment parameters ─────────────────────────────────────────────
BASE_RISK_PCT = 0.02                 # Default 2% risk per trade
WIN_STREAK_RISK_BOOST = 0.005        # +0.5% risk after 2 consecutive wins
MAX_RISK_PCT = 0.03                  # Cap at 3%
MIN_RISK_PCT = 0.015                 # Floor at 1.5%

# Counter-trend penalty multiplier (applied to confidence)
COUNTER_TREND_PENALTY_BASE = 0.90    # 10% confidence haircut
COUNTER_TREND_PENALTY_INCREMENT = 0.03  # +3% penalty per additional CT loss

# Trigger zone widening after fast SL hits
TRIGGER_ZONE_WIDEN_PCT = 0.002       # Widen by 0.2% per fast-SL loss


@dataclass
class SetupStats:
    """Per-setup-type performance statistics."""
    setup_type: str
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0       # Sum of R-multiples
    best_r: float = 0.0        # Best single R
    worst_r: float = 0.0       # Worst single R
    avg_hold_hours: float = 0.0
    fast_sl_count: int = 0     # Times SL hit within 2 bars
    chop_sl_count: int = 0     # Times SL hit after 5+ bars of chop
    last_updated: float = 0.0

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    @property
    def avg_r(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_r / self.total_trades

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["total_trades"] = self.total_trades
        d["win_rate"] = round(self.win_rate, 3)
        d["avg_r"] = round(self.avg_r, 2)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SetupStats":
        # Remove computed fields that aren't constructor params
        d = dict(d)
        d.pop("total_trades", None)
        d.pop("win_rate", None)
        d.pop("avg_r", None)
        return SetupStats(**d)


@dataclass
class TradeLesson:
    """A single lesson extracted from a closed trade."""
    trade_id: str
    symbol: str
    side: str
    setup_type: str
    result: str               # WIN / LOSS
    r_multiple: float         # Actual PnL / risk amount
    diagnosis: str            # What happened (human-readable)
    diagnosis_code: str       # Machine-readable: fast_sl, chop_sl, tp_hit, time_stop, etc.
    adjustment_applied: str   # What adjustment was made
    hold_time_hours: float
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradeLearner:
    """
    Real-time post-trade learning engine.

    Hooks into trade closes from the simulator, analyzes each outcome,
    and immediately adjusts parameters for subsequent trades.
    """

    def __init__(self):
        os.makedirs(_DATA_DIR, exist_ok=True)

        # Per-setup-type stats
        self._setup_stats: Dict[str, SetupStats] = {}

        # Active adjustments (applied to next trade)
        self._risk_pct_override: Optional[float] = None
        self._counter_trend_penalty: float = COUNTER_TREND_PENALTY_BASE
        self._trigger_zone_adjustments: Dict[str, float] = {}  # setup_type -> extra width %
        self._consecutive_wins: int = 0
        self._consecutive_losses: int = 0
        self._system_in_sync: bool = False
        self._needs_entry_map_regen: bool = False

        # Load saved state
        self._load_state()

        logger.info(
            f"[LEARNER] Initialized — {len(self._setup_stats)} setup types tracked, "
            f"streak: W{self._consecutive_wins}/L{self._consecutive_losses}"
        )

    # ── Public API ─────────────────────────────────────────────────────

    def on_trade_close(self, trade) -> TradeLesson:
        """
        Called immediately after a trade closes. Analyzes the outcome and
        applies adjustments for the next trade.

        Args:
            trade: SimTrade (or any object with the same attributes)

        Returns:
            TradeLesson with the diagnosis and adjustments applied.
        """
        # 1. Classify setup type
        setup_type = self._classify_setup(trade)

        # 2. Compute R-multiple
        r_multiple = self._compute_r_multiple(trade)

        # 3. Diagnose what happened
        diagnosis, diagnosis_code = self._diagnose(trade, r_multiple)

        # 4. Update setup stats
        self._update_setup_stats(setup_type, trade, r_multiple)

        # 5. Apply immediate adjustments
        adjustment = self._apply_adjustments(trade, setup_type, diagnosis_code, r_multiple)

        # 6. Build lesson
        lesson = TradeLesson(
            trade_id=getattr(trade, "trade_id", "unknown"),
            symbol=getattr(trade, "symbol", "unknown"),
            side=getattr(trade, "side", "unknown"),
            setup_type=setup_type,
            result=getattr(trade, "result", "unknown"),
            r_multiple=round(r_multiple, 2),
            diagnosis=diagnosis,
            diagnosis_code=diagnosis_code,
            adjustment_applied=adjustment,
            hold_time_hours=getattr(trade, "hold_time_hours", 0.0),
            entry_price=getattr(trade, "entry", 0.0),
            exit_price=getattr(trade, "exit_price", 0.0),
            sl_price=getattr(trade, "sl", 0.0),
            tp_price=getattr(trade, "tp_scalp", 0.0),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 7. Persist
        self._log_lesson(lesson)
        self._save_state()

        logger.info(
            f"[LEARNER] {lesson.trade_id} | {lesson.setup_type} | "
            f"{lesson.result} R={lesson.r_multiple:+.2f} | "
            f"Diagnosis: {lesson.diagnosis_code} | Adj: {lesson.adjustment_applied}"
        )

        return lesson

    def get_setup_weights(self) -> Dict[str, float]:
        """
        Returns a weight multiplier for each known setup type.

        Used by anticipatory_entries and entry_map_generator to bias
        toward setup types that have been winning.

        Returns:
            Dict mapping setup_type -> weight (0.5 to 1.5).
            >1.0 = boost (winning setups), <1.0 = penalize (losing setups).
            Missing setup types get 1.0 (neutral).
        """
        weights: Dict[str, float] = {}

        for stype, stats in self._setup_stats.items():
            if stats.total_trades < 2:
                # Not enough data — neutral weight
                weights[stype] = 1.0
                continue

            # Base weight from win rate (0.5 to 1.5 range)
            # 50% WR = 1.0 weight, 80% WR = 1.3, 20% WR = 0.7
            wr = stats.win_rate
            weight = 0.5 + wr  # Maps 0% -> 0.5, 50% -> 1.0, 100% -> 1.5

            # Bonus for positive average R
            if stats.avg_r > 0:
                weight += min(0.2, stats.avg_r * 0.1)  # Up to +0.2 for high avg R

            # Penalty for frequent fast SL hits (bad entries)
            if stats.total_trades > 0:
                fast_sl_rate = stats.fast_sl_count / stats.total_trades
                if fast_sl_rate > 0.5:
                    weight -= 0.2  # Heavy penalty for frequent bad entries

            # Clamp to [0.3, 1.5]
            weight = max(0.3, min(1.5, weight))
            weights[stype] = round(weight, 2)

        return weights

    def get_risk_pct(self, default: float = BASE_RISK_PCT) -> float:
        """
        Get the current risk percentage, accounting for streak adjustments.

        Returns:
            Float between MIN_RISK_PCT and MAX_RISK_PCT.
        """
        if self._risk_pct_override is not None:
            return self._risk_pct_override
        return default

    def get_counter_trend_penalty(self) -> float:
        """
        Get the current counter-trend confidence penalty multiplier.

        Returns:
            Float between 0.7 and 1.0. Multiply confidence by this value
            for counter-trend trades.
        """
        return self._counter_trend_penalty

    def get_trigger_zone_adjustment(self, setup_type: str) -> float:
        """
        Get extra trigger zone width for a setup type (in %).

        After fast SL hits, the trigger zone is widened to avoid premature entries.

        Returns:
            Float, extra width in decimal (e.g., 0.002 = 0.2%).
        """
        return self._trigger_zone_adjustments.get(setup_type, 0.0)

    def needs_entry_map_regen(self) -> bool:
        """Check if a loss triggered the need for entry map regeneration."""
        if self._needs_entry_map_regen:
            self._needs_entry_map_regen = False  # Reset after check
            return True
        return False

    @property
    def system_in_sync(self) -> bool:
        """True if system is on a 2+ win streak."""
        return self._system_in_sync

    def get_status(self) -> Dict[str, Any]:
        """Return full learner status for dashboards."""
        return {
            "setup_stats": {k: v.to_dict() for k, v in self._setup_stats.items()},
            "setup_weights": self.get_setup_weights(),
            "risk_pct_override": self._risk_pct_override,
            "counter_trend_penalty": self._counter_trend_penalty,
            "trigger_zone_adjustments": self._trigger_zone_adjustments,
            "consecutive_wins": self._consecutive_wins,
            "consecutive_losses": self._consecutive_losses,
            "system_in_sync": self._system_in_sync,
        }

    # ── Internal: Classification ───────────────────────────────────────

    def _classify_setup(self, trade) -> str:
        """
        Classify a trade into a setup type based on available metadata.

        Tries multiple fields: setup_type, source, tier, then falls back
        to symbol_side as a generic type.
        """
        # Check for explicit setup_type (from anticipatory entries)
        setup_type = getattr(trade, "setup_type", None)
        if setup_type and setup_type in SETUP_TYPE_MAP:
            return SETUP_TYPE_MAP[setup_type]
        if setup_type and setup_type != "":
            return setup_type

        # Check for source field (from entry_map_generator)
        source = getattr(trade, "source", None)
        if source and source in SETUP_TYPE_MAP:
            return SETUP_TYPE_MAP[source]

        # Check tier field
        tier = getattr(trade, "tier", "")

        # Fallback: symbol + side as generic setup type
        symbol = getattr(trade, "symbol", "unknown")
        side = getattr(trade, "side", "unknown")
        return f"{symbol}_{side}".lower()

    def _compute_r_multiple(self, trade) -> float:
        """
        Compute the R-multiple: actual PnL / risk amount.

        R=1.0 means the trade returned exactly the risk amount.
        R=-1.0 means the full stop was hit.
        """
        risk_amount = getattr(trade, "risk_amount", 0)
        pnl_usd = getattr(trade, "pnl_usd", 0)

        if risk_amount <= 0:
            # Fallback: estimate risk from SL distance
            entry = getattr(trade, "entry", 0)
            sl = getattr(trade, "sl", 0)
            size = getattr(trade, "position_size_usd", 0)
            if entry > 0 and sl > 0 and size > 0:
                sl_dist_pct = abs(entry - sl) / entry
                risk_amount = size * sl_dist_pct
            else:
                return 0.0

        if risk_amount <= 0:
            return 0.0

        return pnl_usd / risk_amount

    # ── Internal: Diagnosis ────────────────────────────────────────────

    def _diagnose(self, trade, r_multiple: float) -> Tuple[str, str]:
        """
        Diagnose WHY a trade won or lost.

        Returns (human_diagnosis, machine_code).
        """
        result = getattr(trade, "result", "unknown")
        exit_reason = getattr(trade, "exit_reason", "unknown")
        hold_time_s = getattr(trade, "hold_time_s", 0)
        hold_time_h = getattr(trade, "hold_time_hours", 0)
        entry = getattr(trade, "entry", 0)
        exit_price = getattr(trade, "exit_price", 0)
        sl = getattr(trade, "sl", 0)
        tp = getattr(trade, "tp_scalp", 0)

        # ── WIN diagnoses ──
        if result == "WIN":
            if exit_reason == "tp_scalp":
                return (
                    f"TP hit at ${exit_price:.2f} after {hold_time_h:.1f}h. "
                    f"R={r_multiple:+.2f}. Clean execution.",
                    "tp_hit"
                )
            elif exit_reason == "sl_dynamic":
                return (
                    f"Dynamic SL locked profit at ${exit_price:.2f}. "
                    f"R={r_multiple:+.2f}. Trailing stop working.",
                    "trailing_win"
                )
            elif "time_stop" in exit_reason:
                return (
                    f"Time stop but profitable. Price=${exit_price:.2f} vs entry=${entry:.2f}. "
                    f"R={r_multiple:+.2f}. Setup was right but TP was too far.",
                    "time_stop_win"
                )
            return (f"Win via {exit_reason}. R={r_multiple:+.2f}.", "other_win")

        # ── LOSS diagnoses ──
        if exit_reason in ("sl", "sl_dynamic"):
            if hold_time_s < FAST_SL_THRESHOLD_S:
                # Fast SL — entry was bad, price reversed immediately
                return (
                    f"SL hit FAST ({hold_time_h:.1f}h). Entry at ${entry:.2f} was premature. "
                    f"Price reversed to ${exit_price:.2f} within 2 bars. "
                    f"Consider widening trigger zone or waiting for confirmation.",
                    "fast_sl"
                )
            elif hold_time_s >= CHOP_SL_THRESHOLD_S:
                # Slow SL — setup was right but market wasn't ready
                return (
                    f"SL hit after {hold_time_h:.1f}h of chop. Setup was RIGHT "
                    f"but market wasn't ready. Entry=${entry:.2f}, SL=${exit_price:.2f}. "
                    f"Consider: market was ranging, not trending.",
                    "chop_sl"
                )
            else:
                # Normal SL
                return (
                    f"SL hit at ${exit_price:.2f} after {hold_time_h:.1f}h. "
                    f"Normal stop-out. R={r_multiple:+.2f}.",
                    "normal_sl"
                )

        if "time_stop" in exit_reason:
            return (
                f"Time stop loss after {hold_time_h:.1f}h. Price=${exit_price:.2f} "
                f"vs entry=${entry:.2f}. Trade went nowhere — wrong setup or timing.",
                "time_stop_loss"
            )

        return (f"Loss via {exit_reason}. R={r_multiple:+.2f}.", "other_loss")

    # ── Internal: Stats update ─────────────────────────────────────────

    def _update_setup_stats(self, setup_type: str, trade, r_multiple: float) -> None:
        """Update per-setup-type performance statistics."""
        if setup_type not in self._setup_stats:
            self._setup_stats[setup_type] = SetupStats(setup_type=setup_type)

        stats = self._setup_stats[setup_type]
        result = getattr(trade, "result", "LOSS")
        hold_hours = getattr(trade, "hold_time_hours", 0)
        hold_time_s = getattr(trade, "hold_time_s", 0)

        if result == "WIN":
            stats.wins += 1
        else:
            stats.losses += 1

        stats.total_r += r_multiple

        if r_multiple > stats.best_r:
            stats.best_r = round(r_multiple, 2)
        if r_multiple < stats.worst_r:
            stats.worst_r = round(r_multiple, 2)

        # Track fast SL and chop SL
        exit_reason = getattr(trade, "exit_reason", "")
        if result == "LOSS" and exit_reason in ("sl", "sl_dynamic"):
            if hold_time_s < FAST_SL_THRESHOLD_S:
                stats.fast_sl_count += 1
            elif hold_time_s >= CHOP_SL_THRESHOLD_S:
                stats.chop_sl_count += 1

        # Rolling average hold time
        n = stats.total_trades
        if n > 0:
            stats.avg_hold_hours = round(
                ((stats.avg_hold_hours * (n - 1)) + hold_hours) / n, 2
            )

        stats.last_updated = time.time()

    # ── Internal: Adjustments ──────────────────────────────────────────

    def _apply_adjustments(
        self, trade, setup_type: str, diagnosis_code: str, r_multiple: float
    ) -> str:
        """
        Apply immediate parameter adjustments based on trade outcome.

        Returns a description of what was adjusted.
        """
        result = getattr(trade, "result", "LOSS")
        adjustments: List[str] = []

        # ── Streak tracking ──
        if result == "WIN":
            self._consecutive_wins += 1
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0

        # ── After a WIN ──
        if result == "WIN":
            # Record what worked
            adjustments.append(f"recorded_win:{setup_type}")

            # 2 wins in a row: system in sync — allow slightly wider risk
            if self._consecutive_wins >= 2:
                self._system_in_sync = True
                new_risk = min(MAX_RISK_PCT, BASE_RISK_PCT + WIN_STREAK_RISK_BOOST)
                self._risk_pct_override = new_risk
                adjustments.append(f"system_in_sync:risk->{new_risk*100:.1f}%")
            else:
                self._system_in_sync = False

        # ── After a LOSS ──
        if result == "LOSS":
            self._system_in_sync = False

            # Reset risk to base after any loss
            self._risk_pct_override = None
            adjustments.append("risk_reset_to_base")

            # Fast SL: entry was bad — widen trigger zone for this setup type
            if diagnosis_code == "fast_sl":
                current = self._trigger_zone_adjustments.get(setup_type, 0.0)
                new_width = current + TRIGGER_ZONE_WIDEN_PCT
                self._trigger_zone_adjustments[setup_type] = round(new_width, 4)
                adjustments.append(
                    f"widen_trigger:{setup_type}+{TRIGGER_ZONE_WIDEN_PCT*100:.1f}% "
                    f"(total={new_width*100:.1f}%)"
                )

            # Chop SL: setup was right but market wasn't ready
            if diagnosis_code == "chop_sl":
                adjustments.append(f"chop_noted:{setup_type} (market_not_ready)")

            # Check if this was likely counter-trend
            if self._is_counter_trend(trade):
                # Increase counter-trend penalty
                self._counter_trend_penalty = max(
                    0.70,
                    self._counter_trend_penalty - COUNTER_TREND_PENALTY_INCREMENT
                )
                adjustments.append(
                    f"counter_trend_penalty->{self._counter_trend_penalty:.2f}"
                )

            # After any loss: flag for entry map regeneration
            self._needs_entry_map_regen = True
            adjustments.append("entry_map_regen_flagged")

        return "; ".join(adjustments) if adjustments else "none"

    def _is_counter_trend(self, trade) -> bool:
        """
        Heuristic: was this trade likely counter-trend?

        A counter-trend trade is a BUY in a downtrend or SELL in an uptrend.
        We use the regime field if available.
        """
        regime = getattr(trade, "regime", "unknown")
        side = getattr(trade, "side", "unknown")

        # Known trending regimes
        if regime in ("trend", "strong_trend"):
            # In a trend regime, we don't know direction from regime alone,
            # but if the trade lost, it may have been counter-trend.
            # Use entry vs exit as a rough indicator.
            entry = getattr(trade, "entry", 0)
            exit_price = getattr(trade, "exit_price", 0)
            result = getattr(trade, "result", "")
            if result == "LOSS":
                # BUY that lost in trending market — price went down, so downtrend
                if side == "BUY" and exit_price < entry:
                    return True
                # SELL that lost in trending market — price went up, so uptrend
                if side == "SELL" and exit_price > entry:
                    return True

        return False

    # ── Persistence ────────────────────────────────────────────────────

    def _log_lesson(self, lesson: TradeLesson) -> None:
        """Append lesson to JSONL log."""
        try:
            with open(_LESSONS_PATH, "a") as f:
                f.write(json.dumps(lesson.to_dict()) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.warning(f"[LEARNER] Failed to log lesson: {e}")

    def _save_state(self) -> None:
        """Save learner state to JSON."""
        try:
            state = {
                "setup_stats": {k: v.to_dict() for k, v in self._setup_stats.items()},
                "risk_pct_override": self._risk_pct_override,
                "counter_trend_penalty": self._counter_trend_penalty,
                "trigger_zone_adjustments": self._trigger_zone_adjustments,
                "consecutive_wins": self._consecutive_wins,
                "consecutive_losses": self._consecutive_losses,
                "system_in_sync": self._system_in_sync,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp_path = _LEARNER_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, _LEARNER_PATH)
        except Exception as e:
            logger.warning(f"[LEARNER] Failed to save state: {e}")

    def _load_state(self) -> None:
        """Load learner state from JSON."""
        if not os.path.exists(_LEARNER_PATH):
            return
        try:
            with open(_LEARNER_PATH, "r") as f:
                content = f.read().strip()
            if not content:
                return
            state = json.loads(content)

            # Restore setup stats
            for k, v in state.get("setup_stats", {}).items():
                self._setup_stats[k] = SetupStats.from_dict(v)

            self._risk_pct_override = state.get("risk_pct_override")
            self._counter_trend_penalty = state.get(
                "counter_trend_penalty", COUNTER_TREND_PENALTY_BASE
            )
            self._trigger_zone_adjustments = state.get("trigger_zone_adjustments", {})
            self._consecutive_wins = state.get("consecutive_wins", 0)
            self._consecutive_losses = state.get("consecutive_losses", 0)
            self._system_in_sync = state.get("system_in_sync", False)

        except Exception as e:
            logger.warning(f"[LEARNER] Failed to load state, starting fresh: {e}")
