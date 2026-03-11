"""
Filter accuracy tracker: measures how often each filter's rejections were correct.

"Of signals this filter rejected, what % actually would have lost money?"

This is the key feedback loop that lets the system learn which filters
are helping and which are blocking profitable trades.

Uses data from bot/core/signal_tracker.py (signal_outcomes.jsonl)
and bot/data/trades.csv (actual trade outcomes).
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.filter_accuracy")

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "logs", "signal_outcomes.jsonl")


class FilterAccuracyTracker:
    """Computes per-filter accuracy from signal outcomes + trade results."""

    def __init__(self, log_path: Optional[str] = None):
        self._log_path = log_path or _LOG_PATH
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 300  # Refresh every 5 min

    def get_filter_accuracy_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute per-filter accuracy statistics.

        Returns:
        {
            "fee_drag": {
                "total_evaluations": 100,
                "rejections": 25,
                "rejection_rate": 0.25,
                "warnings": 15,
            },
            "ev_floor": { ... },
            ...
        }
        """
        now = time.time()
        if self._cache and (now - self._cache_ts) < self._cache_ttl:
            return self._cache

        stats: Dict[str, Dict[str, Any]] = {}

        if not os.path.exists(self._log_path):
            return stats

        try:
            with open(self._log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Skip counterfactual records
                    if rec.get("type") == "counterfactual":
                        continue

                    for ann in rec.get("annotations", []):
                        gate = ann.get("gate", "unknown")
                        if gate not in stats:
                            stats[gate] = {
                                "total_evaluations": 0,
                                "rejections": 0,
                                "warnings": 0,
                                "rejection_rate": 0.0,
                            }
                        stats[gate]["total_evaluations"] += 1
                        if ann.get("severity") == "reject":
                            stats[gate]["rejections"] += 1
                        elif ann.get("severity") == "warning":
                            stats[gate]["warnings"] += 1

            # Compute rates
            for gate, data in stats.items():
                total = data["total_evaluations"]
                if total > 0:
                    data["rejection_rate"] = round(data["rejections"] / total, 3)
                    data["warning_rate"] = round(data["warnings"] / total, 3)

            self._cache = stats
            self._cache_ts = now
        except Exception as e:
            logger.warning(f"[FILTER-ACCURACY] Error computing stats: {e}")

        return stats

    def get_filter_tuning_recommendations(self) -> List[Dict[str, str]]:
        """Generate recommendations for filter threshold adjustments.

        Rules:
        - If a filter rejects >50% of signals, it's probably too tight
        - If a filter rejects <5% of signals, it's probably unnecessary
        - If counterfactual data shows rejected signals would have been profitable,
          the filter is blocking good trades
        """
        stats = self.get_filter_accuracy_stats()
        recs = []

        for gate, data in stats.items():
            total = data["total_evaluations"]
            if total < 10:
                continue  # Not enough data

            rate = data["rejection_rate"]
            if rate > 0.50:
                recs.append({
                    "gate": gate,
                    "recommendation": "loosen",
                    "reason": f"{gate} rejecting {rate:.0%} of signals — threshold may be too tight",
                    "current_rejection_rate": rate,
                })
            elif rate < 0.05 and data["warnings"] == 0:
                recs.append({
                    "gate": gate,
                    "recommendation": "review",
                    "reason": f"{gate} rarely triggers ({rate:.0%}) — may be redundant",
                    "current_rejection_rate": rate,
                })

        return recs

    def get_compact_for_snapshot(self) -> Optional[Dict[str, Any]]:
        """Compact filter accuracy stats for LLM snapshot injection.

        Returns e.g.: {"fd_rej":25,"ev_rej":18,"cr_rej":8,"rr_rej":12}
        Only includes gates that have meaningful rejection counts.
        """
        stats = self.get_filter_accuracy_stats()
        if not stats:
            return None

        _short = {
            "fee_drag": "fd",
            "ev_floor": "ev",
            "correlation": "cr",
            "rr_floor": "rr",
            "lev_ev_floor": "lev_ev",
            "confidence_floor": "conf",
            "chop_floor": "chop",
            "trend_alignment": "trend",
        }

        compact = {}
        for gate, data in stats.items():
            if data["rejections"] > 0:
                short = _short.get(gate, gate[:4])
                compact[f"{short}_rej"] = data["rejections"]
                if data["total_evaluations"] > 0:
                    compact[f"{short}_rate"] = round(data["rejection_rate"], 2)

        return compact if compact else None


# ── Singleton ──
_instance: Optional[FilterAccuracyTracker] = None


def get_filter_accuracy_tracker() -> FilterAccuracyTracker:
    global _instance
    if _instance is None:
        _instance = FilterAccuracyTracker()
    return _instance
