"""
Rejection Outcome Tracker — Measures whether rejected signals would have been profitable.

This is Phase 1 of the Adaptive Online Learning System. It:
1. Records every rejected signal with price + context at rejection time
2. Periodically measures price movement at 30/60/120/240 min windows
3. Classifies outcomes as: missed_profit, correct_rejection, inconclusive
4. Feeds results to EVCalibrator for threshold adjustment (Phase 2)

Designed to be wired into the ensemble after EV gate rejection.

Evidence from paper trading session 2026-03-23:
- Strongly negative EV (< -0.05): 100% correct rejections
- Marginally negative EV (>= -0.01): 50%+ became profitable when 3+ strategies agreed
- The EV gate has a clean separation — marginal zone needs adaptive calibration
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.feedback.rejection_tracker")

MEASUREMENT_WINDOWS = [30, 60, 120, 240]  # Minutes after rejection


@dataclass
class RejectionRecord:
    """A single rejected signal with outcome tracking."""
    symbol: str
    side: str
    n_agree: int
    ev: float
    win_prob: float
    entry_price: float
    rsi: float = 0.0
    regime: str = "unknown"
    timestamp: float = 0.0
    outcomes: Dict[int, float] = field(default_factory=dict)  # {window_min: move_pct}
    final_outcome: str = ""  # missed_profit, correct_rejection, inconclusive
    archived: bool = False


class RejectionOutcomeTracker:
    """Tracks rejected signals and measures if they would have been profitable.

    Wire into ensemble.py after EV rejection:
        if ev_per_dollar < 0:
            self._rejection_tracker.record(symbol, side, n_agree, ev, win_prob, price, ...)
            return None

    Call measure_outcomes() every scan cycle with current prices.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._pending: List[RejectionRecord] = []
        self._completed: List[RejectionRecord] = []
        self._file = os.path.join(data_dir, "rejection_outcomes.jsonl")

        # Statistics by EV bin
        self.bins = {
            "strong_neg": {"range": (-1.0, -0.05), "missed": 0, "correct": 0, "total": 0},
            "moderate_neg": {"range": (-0.05, -0.01), "missed": 0, "correct": 0, "total": 0},
            "marginal_neg": {"range": (-0.01, 0.0), "missed": 0, "correct": 0, "total": 0},
        }

        # Consensus-specific stats
        self.consensus_stats = {
            "solo": {"missed": 0, "correct": 0, "total": 0},       # 1 strategy
            "pair": {"missed": 0, "correct": 0, "total": 0},       # 2 strategies
            "consensus": {"missed": 0, "correct": 0, "total": 0},  # 3+ strategies
        }

        # Callback for EVCalibrator integration
        self._outcome_callback = None  # Set externally: fn(ev, n_agree, outcome)

        # Deduplication: don't record same symbol+side within 5 min
        self._last_recorded: Dict[str, float] = {}
        self._cooldown_s = 300  # 5 minutes

        # Load existing data
        self._load()

        logger.info(
            f"[REJECTION-TRACKER] Initialized: {len(self._pending)} pending, "
            f"{len(self._completed)} completed"
        )

    def record(
        self,
        symbol: str,
        side: str,
        n_agree: int,
        ev: float,
        win_prob: float,
        price: float,
        rsi: float = 0.0,
        regime: str = "unknown",
    ) -> None:
        """Record a new rejection for outcome tracking."""
        # Dedup: skip if same symbol+side recorded recently
        key = f"{symbol}_{side}"
        now = time.time()
        if key in self._last_recorded and (now - self._last_recorded[key]) < self._cooldown_s:
            return
        self._last_recorded[key] = now

        rec = RejectionRecord(
            symbol=symbol,
            side=side,
            n_agree=n_agree,
            ev=ev,
            win_prob=win_prob,
            entry_price=price,
            rsi=rsi,
            regime=regime,
            timestamp=now,
        )
        self._pending.append(rec)
        logger.debug(
            f"[REJECTION-TRACKER] Recorded: {symbol} {side} EV={ev:.4f} "
            f"n_agree={n_agree} price=${price:,.2f}"
        )

    def measure_outcomes(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Check pending rejections against current prices.

        Call this every scan cycle. Returns list of newly completed outcomes.
        """
        now = time.time()
        newly_completed = []

        for rec in self._pending:
            if rec.archived:
                continue

            age_min = (now - rec.timestamp) / 60
            current = current_prices.get(rec.symbol)
            if not current:
                continue

            # Calculate move in signal direction
            if rec.side == "SELL":
                move_pct = (rec.entry_price - current) / rec.entry_price * 100
            else:
                move_pct = (current - rec.entry_price) / rec.entry_price * 100

            # Record at each measurement window
            for window in MEASUREMENT_WINDOWS:
                if age_min >= window and window not in rec.outcomes:
                    rec.outcomes[window] = round(move_pct, 4)

            # After longest window, classify and archive
            if age_min >= max(MEASUREMENT_WINDOWS) and not rec.archived:
                self._classify(rec)
                newly_completed.append(asdict(rec))

        # Clean up archived
        self._pending = [r for r in self._pending if not r.archived]

        # Persist
        if newly_completed:
            self._save_completed(newly_completed)

        return newly_completed

    # Classification constants (FALLACY_AUDIT M9, 2026-07-02)
    CLASSIFY_THRESHOLD_PCT = 1.0   # symmetric win/loss bar on NET move
    ROUND_TRIP_FEE_PCT = 0.10      # est. taker fees both ways, pct of notional

    @classmethod
    def classify_moves(cls, outcomes: Dict) -> str:
        """First-touch classification over windowed move snapshots.

        FALLACY_AUDIT M9 (2026-07-02): the old rule took max() over all
        windows > +1.0% as "missed_profit" EVEN IF -0.5% was breached first
        (look-ahead best-excursion; a stop-out counted as a miss), with
        asymmetric thresholds and no fees. This inflated miss_rate and pushed
        the EVCalibrator toward RELAXED. Now: walk windows in TIME order; the
        first window whose fee-adjusted move breaches the symmetric +/-1.0%
        bar decides. (True path ordering needs candles; window order is the
        best available proxy on stored snapshots.)
        """
        if not outcomes:
            return "inconclusive"
        # JSON round-trips turn int keys into strings — normalize
        try:
            seq = sorted(((int(k), float(v)) for k, v in outcomes.items()))
        except (ValueError, TypeError):
            return "inconclusive"
        for _window, move in seq:
            net = move - cls.ROUND_TRIP_FEE_PCT  # a taken trade pays fees
            if net >= cls.CLASSIFY_THRESHOLD_PCT:
                return "missed_profit"
            if net <= -cls.CLASSIFY_THRESHOLD_PCT:
                return "correct_rejection"
        return "inconclusive"

    def _classify(self, rec: RejectionRecord) -> None:
        """Classify rejection outcome and update statistics."""
        rec.final_outcome = self.classify_moves(rec.outcomes)
        if rec.final_outcome == "inconclusive" and not rec.outcomes:
            rec.archived = True
            return

        rec.archived = True
        self._completed.append(rec)

        # Update bin stats
        for name, config in self.bins.items():
            lo, hi = config["range"]
            if lo <= rec.ev < hi:
                config["total"] += 1
                if rec.final_outcome == "missed_profit":
                    config["missed"] += 1
                elif rec.final_outcome == "correct_rejection":
                    config["correct"] += 1
                break

        # Update consensus stats
        if rec.n_agree >= 3:
            bucket = "consensus"
        elif rec.n_agree >= 2:
            bucket = "pair"
        else:
            bucket = "solo"
        self.consensus_stats[bucket]["total"] += 1
        if rec.final_outcome == "missed_profit":
            self.consensus_stats[bucket]["missed"] += 1
        elif rec.final_outcome == "correct_rejection":
            self.consensus_stats[bucket]["correct"] += 1

        logger.info(
            f"[REJECTION-TRACKER] Outcome: {rec.symbol} {rec.side} "
            f"EV={rec.ev:.4f} n_agree={rec.n_agree} -> {rec.final_outcome} "
            f"(first-touch over windows {sorted(rec.outcomes.keys()) if rec.outcomes else []})"
        )

        # Feed outcome to EVCalibrator
        if self._outcome_callback is not None:
            try:
                self._outcome_callback(rec.ev, rec.n_agree, rec.final_outcome)
            except Exception as e:
                logger.debug(f"[REJECTION-TRACKER] Callback error: {e}")

    def get_miss_rate(self, ev_bin: str = "marginal_neg") -> float:
        """Get missed profit rate for an EV bin."""
        b = self.bins.get(ev_bin, {})
        if b.get("total", 0) == 0:
            return 0.0
        return b["missed"] / b["total"]

    def get_consensus_miss_rate(self) -> float:
        """Get missed profit rate for 3+ strategy consensus signals."""
        c = self.consensus_stats["consensus"]
        if c["total"] == 0:
            return 0.0
        return c["missed"] / c["total"]

    def get_stats_summary(self) -> Dict[str, Any]:
        """Get summary statistics for logging/reporting."""
        return {
            "pending": len(self._pending),
            "completed": len(self._completed),
            "bins": {k: {kk: vv for kk, vv in v.items() if kk != "range"}
                     for k, v in self.bins.items()},
            "consensus": self.consensus_stats,
        }

    def _save_completed(self, records: List[Dict]) -> None:
        """Append completed outcomes to JSONL file."""
        try:
            os.makedirs(os.path.dirname(self._file), exist_ok=True)
            with open(self._file, "a") as f:
                for rec in records:
                    f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[REJECTION-TRACKER] Save error: {e}")

    def _load(self) -> None:
        """Load completed outcomes from disk to rebuild statistics."""
        if not os.path.exists(self._file):
            return
        try:
            with open(self._file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec_dict = json.loads(line)
                    # Rebuild stats from completed records.
                    # FALLACY_AUDIT M9: RE-SCORE with the first-touch
                    # classifier rather than trusting stored verdicts — the
                    # backlog was graded by the look-ahead best-excursion rule.
                    ev = rec_dict.get("ev", 0)
                    _stored_moves = rec_dict.get("outcomes") or {}
                    outcome = (
                        self.classify_moves(_stored_moves)
                        if _stored_moves else rec_dict.get("final_outcome", "")
                    )
                    n_agree = rec_dict.get("n_agree", 1)

                    for name, config in self.bins.items():
                        lo, hi = config["range"]
                        if lo <= ev < hi:
                            config["total"] += 1
                            if outcome == "missed_profit":
                                config["missed"] += 1
                            elif outcome == "correct_rejection":
                                config["correct"] += 1
                            break

                    bucket = "consensus" if n_agree >= 3 else "pair" if n_agree >= 2 else "solo"
                    self.consensus_stats[bucket]["total"] += 1
                    if outcome == "missed_profit":
                        self.consensus_stats[bucket]["missed"] += 1
                    elif outcome == "correct_rejection":
                        self.consensus_stats[bucket]["correct"] += 1

            logger.debug(f"[REJECTION-TRACKER] Loaded stats from {self._file}")
        except Exception as e:
            logger.warning(f"[REJECTION-TRACKER] Load error: {e}")
