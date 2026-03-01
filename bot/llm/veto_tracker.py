"""
Veto Counterfactual Validator: What would have happened?

When the LLM vetoes a trade (action=skip/flat in VETO_ONLY+), this module
records the signal and periodically checks what would have happened if
the trade had been taken.

This closes the critical "veto feedback loop" — without it, the LLM never
knows if its vetoes were correct, leading to uncalibrated risk aversion.

Data flow:
  1. LLM vetoes a signal → record_veto() stores entry/SL/TP + prices
  2. Every 10 minutes → check_outcomes() evaluates each pending veto
  3. Results fed back → self_performance.py uses them for veto_accuracy
  4. Persists to data/llm/veto_history.json (rolling 200 entries)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.llm.veto_tracker")

_VETO_DIR = os.path.join("data", "llm")
_VETO_PATH = os.path.join(_VETO_DIR, "veto_history.json")
_MAX_HISTORY = 200
_CHECK_INTERVAL_S = 600  # 10 minutes
_MIN_AGE_FOR_CHECK_S = 3600  # 1 hour before checking outcome
_MAX_AGE_S = 14400  # 4 hours — stop checking after this


@dataclass
class VetoRecord:
    """A vetoed signal with its counterfactual outcome."""
    timestamp: float = 0.0
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    confidence: float = 0.0
    llm_confidence: float = 0.0
    llm_reason: str = ""
    regime: str = ""
    # Filled after evaluation:
    outcome: str = ""          # "WOULD_WIN", "WOULD_LOSE", "UNKNOWN", "PENDING"
    price_after_1h: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    checked_at: float = 0.0


class VetoTracker:
    """Tracks vetoed signals and evaluates counterfactual outcomes."""

    def __init__(self):
        self._pending: List[VetoRecord] = []
        self._resolved: List[Dict[str, Any]] = []
        self._last_check: float = 0.0
        self._load_state()

    def record_veto(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        confidence: float = 0.0,
        llm_confidence: float = 0.0,
        llm_reason: str = "",
        regime: str = "",
    ):
        """Record a vetoed signal for counterfactual tracking."""
        if not symbol or entry_price <= 0:
            return

        record = VetoRecord(
            timestamp=time.time(),
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            confidence=confidence,
            llm_confidence=llm_confidence,
            llm_reason=llm_reason[:200] if llm_reason else "",
            regime=regime,
            outcome="PENDING",
        )
        self._pending.append(record)

        logger.info(
            f"[VETO] Recorded: {symbol} {side} entry={entry_price:.4f} "
            f"SL={sl_price:.4f} TP1={tp1_price:.4f} "
            f"(ensemble_conf={confidence:.0f}%, llm_conf={llm_confidence:.2f})"
        )

    def check_outcomes(self, price_fetcher=None):
        """Check counterfactual outcomes for pending vetoes.

        Args:
            price_fetcher: Callable(symbol) -> float, returns current price.
                           Typically fetcher.get_current_price() from DataFetcher.
        """
        now = time.time()
        if now - self._last_check < _CHECK_INTERVAL_S:
            return
        self._last_check = now

        if not self._pending or not price_fetcher:
            return

        still_pending = []
        for record in self._pending:
            age = now - record.timestamp

            # Too young — wait for price to develop
            if age < _MIN_AGE_FOR_CHECK_S:
                still_pending.append(record)
                continue

            # Too old — mark unknown and archive
            if age > _MAX_AGE_S:
                record.outcome = "UNKNOWN"
                record.checked_at = now
                self._archive_record(record)
                continue

            # Evaluate: would SL or TP1 have been hit?
            try:
                current_price = price_fetcher(record.symbol)
                if current_price is None or current_price <= 0:
                    still_pending.append(record)
                    continue

                record.price_after_1h = current_price
                outcome = self._evaluate_outcome(record, current_price)
                record.outcome = outcome
                record.checked_at = now

                logger.info(
                    f"[VETO] {record.symbol} {record.side}: {outcome} "
                    f"(entry={record.entry_price:.4f} now={current_price:.4f})"
                )

                self._archive_record(record)
            except Exception as e:
                logger.warning(f"[VETO] Failed to check {record.symbol}: {e}")
                still_pending.append(record)

        self._pending = still_pending
        self._save_state()

    def _evaluate_outcome(self, record: VetoRecord, current_price: float) -> str:
        """Determine if the vetoed trade would have won or lost.

        Simple heuristic: check if price moved favorably enough to hit TP1,
        or adversely enough to hit SL.
        """
        entry = record.entry_price
        sl = record.sl_price
        tp1 = record.tp1_price

        if record.side.upper() in ("LONG", "BUY"):
            # Long: TP1 is above entry, SL is below
            favorable_move = current_price - entry
            adverse_move = entry - current_price

            # Would TP1 have been hit?
            if tp1 > 0 and current_price >= tp1:
                return "WOULD_WIN"
            # Would SL have been hit?
            if sl > 0 and current_price <= sl:
                return "WOULD_LOSE"
            # Price is between SL and TP1 — check direction
            if favorable_move > 0:
                # Moving favorably — likely would win
                if tp1 > 0 and favorable_move >= (tp1 - entry) * 0.5:
                    return "WOULD_WIN"
            if adverse_move > 0:
                # Moving adversely — likely would lose
                if sl > 0 and adverse_move >= (entry - sl) * 0.5:
                    return "WOULD_LOSE"

        elif record.side.upper() in ("SHORT", "SELL"):
            # Short: TP1 is below entry, SL is above
            favorable_move = entry - current_price
            adverse_move = current_price - entry

            if tp1 > 0 and current_price <= tp1:
                return "WOULD_WIN"
            if sl > 0 and current_price >= sl:
                return "WOULD_LOSE"
            if favorable_move > 0:
                if tp1 > 0 and favorable_move >= (entry - tp1) * 0.5:
                    return "WOULD_WIN"
            if adverse_move > 0:
                if sl > 0 and adverse_move >= (sl - entry) * 0.5:
                    return "WOULD_LOSE"

        return "UNKNOWN"

    def _archive_record(self, record: VetoRecord):
        """Move a resolved record to the history."""
        self._resolved.append(asdict(record))
        # Keep rolling history
        if len(self._resolved) > _MAX_HISTORY:
            self._resolved = self._resolved[-_MAX_HISTORY:]

    def get_resolved_vetoes(self) -> List[Dict]:
        """Get all resolved veto records (for self_performance)."""
        return self._resolved

    def get_pending_count(self) -> int:
        return len(self._pending)

    def get_stats(self) -> Dict[str, Any]:
        """Get veto tracker summary stats."""
        resolved = self._resolved
        if not resolved:
            return {"pending": len(self._pending), "resolved": 0}

        would_win = sum(1 for r in resolved if r.get("outcome") == "WOULD_WIN")
        would_lose = sum(1 for r in resolved if r.get("outcome") == "WOULD_LOSE")
        unknown = sum(1 for r in resolved if r.get("outcome") == "UNKNOWN")

        total_decided = would_win + would_lose
        veto_accuracy = would_lose / total_decided if total_decided > 0 else 0.5

        return {
            "pending": len(self._pending),
            "resolved": len(resolved),
            "would_win": would_win,
            "would_lose": would_lose,
            "unknown": unknown,
            "veto_accuracy": round(veto_accuracy, 3),
        }

    def _save_state(self):
        """Persist state to disk."""
        os.makedirs(_VETO_DIR, exist_ok=True)
        try:
            state = {
                "pending": [asdict(r) for r in self._pending],
                "resolved": self._resolved[-_MAX_HISTORY:],
            }
            with open(_VETO_PATH, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"[VETO] Failed to save state: {e}")

    def _load_state(self):
        """Load state from disk."""
        if not os.path.exists(_VETO_PATH):
            return
        try:
            with open(_VETO_PATH, "r") as f:
                state = json.load(f)

            # Restore pending records
            for d in state.get("pending", []):
                record = VetoRecord(**{
                    k: v for k, v in d.items()
                    if k in VetoRecord.__dataclass_fields__
                })
                self._pending.append(record)

            self._resolved = state.get("resolved", [])

            logger.info(
                f"[VETO] Loaded: {len(self._pending)} pending, "
                f"{len(self._resolved)} resolved"
            )
        except Exception as e:
            logger.warning(f"[VETO] Failed to load state: {e}")


# Module-level singleton
_tracker: Optional[VetoTracker] = None


def get_veto_tracker() -> VetoTracker:
    """Get or create the singleton VetoTracker."""
    global _tracker
    if _tracker is None:
        _tracker = VetoTracker()
    return _tracker
