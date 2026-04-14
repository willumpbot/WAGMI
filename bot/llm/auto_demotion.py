"""
Auto-demotion safety net for LLM MODE=5 (FULL AUTONOMY).

When the brain degrades (WR drops, drawdown spikes, costs explode),
auto-demote to MODE=3 (SIZING) until metrics recover. Auto-promote
back when brain proves itself again.

Called after every trade close from multi_strategy_main.py.
"""

import logging
import os
import json
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("bot.llm.auto_demotion")

_DEMOTION_LOG = os.path.join("data", "llm", "auto_demotion.json")
_MIN_TRADES_FOR_EVAL = 15  # Need at least this many LLM-influenced trades

# Demotion thresholds — if brain crosses ANY of these, demote
DEMOTION_THRESHOLDS = {
    "min_wr": 0.25,              # WR drops below 25% over last 30 trades
    "max_daily_cost_usd": 5.0,   # Daily LLM spend exceeds $5
    "max_drawdown_pct": 0.12,    # 12% drawdown from peak equity
    "max_skip_rate": 0.60,       # Brain skipping >60% of signals (reverting to blocking)
    "max_error_rate": 0.40,      # >40% of LLM calls failing
}

# Promotion thresholds — brain earns back full autonomy when ALL are met
PROMOTION_THRESHOLDS = {
    "min_wr": 0.32,              # WR >= 32% over last 30 trades
    "min_trades": 20,            # At least 20 trades since demotion
    "max_daily_cost_usd": 3.0,   # Cost under control
    "max_error_rate": 0.20,      # Error rate under 20%
}


class AutoDemotion:
    """Monitors brain metrics and auto-demotes/promotes LLM mode."""

    def __init__(self):
        self._state = self._load_state()

    def _load_state(self) -> dict:
        try:
            if os.path.exists(_DEMOTION_LOG):
                with open(_DEMOTION_LOG) as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "current_mode": int(os.getenv("LLM_MODE", "5")),
            "original_mode": int(os.getenv("LLM_MODE", "5")),
            "demoted": False,
            "demotion_reason": None,
            "demotion_ts": None,
            "trades_since_demotion": 0,
            "last_check_ts": None,
        }

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(_DEMOTION_LOG), exist_ok=True)
            with open(_DEMOTION_LOG, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"Failed to save demotion state: {e}")

    def check_after_trade(
        self,
        recent_trades: list,
        daily_cost_usd: float = 0.0,
        drawdown_pct: float = 0.0,
        skip_rate: float = 0.0,
        error_rate: float = 0.0,
    ) -> Optional[int]:
        """Check brain health after a trade close.

        Returns new LLM mode if changed, None if no change.
        """
        self._state["last_check_ts"] = datetime.now(timezone.utc).isoformat()

        if len(recent_trades) < _MIN_TRADES_FOR_EVAL:
            return None

        # Calculate WR from recent trades
        wins = sum(1 for t in recent_trades if t.get("pnl", 0) > 0)
        wr = wins / len(recent_trades) if recent_trades else 0

        if not self._state["demoted"]:
            # Check for demotion
            reasons = []
            if wr < DEMOTION_THRESHOLDS["min_wr"]:
                reasons.append(f"WR={wr:.0%} < {DEMOTION_THRESHOLDS['min_wr']:.0%}")
            if daily_cost_usd > DEMOTION_THRESHOLDS["max_daily_cost_usd"]:
                reasons.append(f"cost=${daily_cost_usd:.2f} > ${DEMOTION_THRESHOLDS['max_daily_cost_usd']}")
            if drawdown_pct > DEMOTION_THRESHOLDS["max_drawdown_pct"]:
                reasons.append(f"DD={drawdown_pct:.1%} > {DEMOTION_THRESHOLDS['max_drawdown_pct']:.0%}")
            if skip_rate > DEMOTION_THRESHOLDS["max_skip_rate"]:
                reasons.append(f"skip_rate={skip_rate:.0%} > {DEMOTION_THRESHOLDS['max_skip_rate']:.0%}")
            if error_rate > DEMOTION_THRESHOLDS["max_error_rate"]:
                reasons.append(f"error_rate={error_rate:.0%} > {DEMOTION_THRESHOLDS['max_error_rate']:.0%}")

            if reasons:
                self._demote(reasons)
                return self._state["current_mode"]
        else:
            # Check for promotion back
            self._state["trades_since_demotion"] += 1
            if (
                wr >= PROMOTION_THRESHOLDS["min_wr"]
                and self._state["trades_since_demotion"] >= PROMOTION_THRESHOLDS["min_trades"]
                and daily_cost_usd <= PROMOTION_THRESHOLDS["max_daily_cost_usd"]
                and error_rate <= PROMOTION_THRESHOLDS["max_error_rate"]
            ):
                self._promote()
                return self._state["current_mode"]

        return None

    def _demote(self, reasons: list):
        """Demote from MODE=5 to MODE=3."""
        old_mode = self._state["current_mode"]
        new_mode = 3  # SIZING — mechanical trades, LLM sizes
        self._state["demoted"] = True
        self._state["current_mode"] = new_mode
        self._state["demotion_reason"] = "; ".join(reasons)
        self._state["demotion_ts"] = datetime.now(timezone.utc).isoformat()
        self._state["trades_since_demotion"] = 0
        self._save_state()
        logger.warning(
            f"[AUTO-DEMOTION] MODE {old_mode} -> {new_mode}. "
            f"Reasons: {'; '.join(reasons)}"
        )

    def _promote(self):
        """Promote back to original mode."""
        old_mode = self._state["current_mode"]
        new_mode = self._state["original_mode"]
        self._state["demoted"] = False
        self._state["current_mode"] = new_mode
        self._state["demotion_reason"] = None
        self._state["demotion_ts"] = None
        self._state["trades_since_demotion"] = 0
        self._save_state()
        logger.info(
            f"[AUTO-PROMOTION] MODE {old_mode} -> {new_mode}. "
            f"Brain metrics recovered."
        )

    @property
    def is_demoted(self) -> bool:
        return self._state["demoted"]

    @property
    def current_mode(self) -> int:
        return self._state["current_mode"]

    def get_status(self) -> dict:
        return dict(self._state)


# Singleton
_instance: Optional[AutoDemotion] = None


def get_auto_demotion() -> AutoDemotion:
    global _instance
    if _instance is None:
        _instance = AutoDemotion()
    return _instance
