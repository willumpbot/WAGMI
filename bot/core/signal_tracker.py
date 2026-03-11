"""
Signal tracker: records ALL evaluated signals (passed, soft-rejected, hard-rejected)
for filter accuracy analysis and LLM learning.

Previously, rejected signals vanished — the LLM never learned from them.
Now every signal evaluation is logged with full filter annotations,
and counterfactual outcomes are tracked when possible.

Data written to: bot/data/logs/signal_outcomes.jsonl
Retention: 30 days with auto-compaction.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.core.signal_tracker")

# Default path — can be overridden for testing
_DEFAULT_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "logs")
_LOG_FILENAME = "signal_outcomes.jsonl"
_MAX_AGE_DAYS = 30
_COMPACT_EVERY_N = 500  # Compact file every N writes


class SignalTracker:
    """Tracks all signal evaluations for filter accuracy feedback."""

    def __init__(self, log_dir: Optional[str] = None):
        self._log_dir = log_dir or _DEFAULT_LOG_DIR
        os.makedirs(self._log_dir, exist_ok=True)
        self._log_path = os.path.join(self._log_dir, _LOG_FILENAME)
        self._write_count = 0
        self._recent_records: List[Dict[str, Any]] = []  # In-memory buffer (last 100)
        self._max_recent = 100

    def record_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        strategy: str,
        passed: bool,
        hard_rejected: bool,
        hard_rejection_reason: str = "",
        annotations: Optional[List[Dict[str, Any]]] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
        num_strategies_agree: int = 0,
        regime: str = "",
    ):
        """Record a signal evaluation outcome.

        Called for EVERY signal that reaches the filter chain, regardless
        of whether it was approved, soft-rejected, or hard-rejected.
        """
        record = {
            "ts": time.time(),
            "sym": symbol,
            "side": side,
            "conf": round(confidence, 2),
            "strat": strategy,
            "passed": passed,
            "hard_rej": hard_rejected,
            "n_agree": num_strategies_agree,
            "regime": regime,
        }
        if hard_rejection_reason:
            record["rej_reason"] = hard_rejection_reason[:100]
        if annotations:
            record["annotations"] = annotations
        if filter_metadata:
            # Only keep relevant fields to save space
            compact_meta = {}
            for k in ("fee_drag_pct", "ev_per_dollar", "cluster_risk",
                       "leverage", "leverage_tier", "chop_score_smoothed",
                       "effective_confidence_floor", "rr_tp1"):
                if k in filter_metadata:
                    compact_meta[k] = filter_metadata[k]
            if compact_meta:
                record["meta"] = compact_meta

        # Buffer in memory
        self._recent_records.append(record)
        if len(self._recent_records) > self._max_recent:
            self._recent_records = self._recent_records[-self._max_recent:]

        # Write to disk
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._write_count += 1

            if self._write_count % _COMPACT_EVERY_N == 0:
                self._compact()
        except Exception as e:
            logger.warning(f"[SIGNAL-TRACKER] Write error: {e}")

    def record_counterfactual(
        self,
        symbol: str,
        side: str,
        ts_evaluated: float,
        price_at_eval: float,
        price_after_4h: float,
        would_have_hit_tp: bool,
        would_have_hit_sl: bool,
    ):
        """Record what happened to a rejected signal (counterfactual tracking).

        Called asynchronously when price data becomes available for a
        previously-rejected signal's timeframe.
        """
        record = {
            "ts": time.time(),
            "type": "counterfactual",
            "sym": symbol,
            "side": side,
            "ts_eval": ts_evaluated,
            "price_eval": price_at_eval,
            "price_4h": price_after_4h,
            "hit_tp": would_have_hit_tp,
            "hit_sl": would_have_hit_sl,
            "move_pct": round((price_after_4h - price_at_eval) / price_at_eval * 100, 2)
                        if price_at_eval > 0 else 0,
        }
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except Exception as e:
            logger.warning(f"[SIGNAL-TRACKER] Counterfactual write error: {e}")

    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent signal records from memory buffer."""
        return self._recent_records[-limit:]

    def get_filter_rejection_stats(self) -> Dict[str, Dict[str, int]]:
        """Compute per-filter rejection counts from recent signals.

        Returns: {"fee_drag": {"total": 20, "rejected": 8}, ...}
        """
        stats: Dict[str, Dict[str, int]] = {}
        for rec in self._recent_records:
            for ann in rec.get("annotations", []):
                gate = ann.get("gate", "unknown")
                if gate not in stats:
                    stats[gate] = {"total": 0, "rejected": 0, "warned": 0}
                stats[gate]["total"] += 1
                if ann.get("severity") == "reject":
                    stats[gate]["rejected"] += 1
                elif ann.get("severity") == "warning":
                    stats[gate]["warned"] += 1
        return stats

    def get_near_miss_summary(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent near-miss signals (soft-rejected, not hard-rejected).

        These are the most interesting for the LLM — signals that were
        quantitatively borderline but might have qualitative merit.
        """
        near_misses = []
        for rec in reversed(self._recent_records):
            if rec.get("hard_rej"):
                continue
            if not rec.get("passed"):
                near_misses.append({
                    "sym": rec["sym"],
                    "side": rec["side"],
                    "conf": rec["conf"],
                    "strat": rec["strat"],
                    "regime": rec.get("regime", ""),
                    "annotations": rec.get("annotations", []),
                })
                if len(near_misses) >= limit:
                    break
        return near_misses

    def _compact(self):
        """Remove records older than _MAX_AGE_DAYS."""
        if not os.path.exists(self._log_path):
            return
        try:
            cutoff = time.time() - _MAX_AGE_DAYS * 86400
            kept = []
            with open(self._log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("ts", 0) >= cutoff:
                            kept.append(line)
                    except json.JSONDecodeError:
                        continue

            with open(self._log_path, "w") as f:
                for line in kept:
                    f.write(line + "\n")

            logger.info(f"[SIGNAL-TRACKER] Compacted: kept {len(kept)} records")
        except Exception as e:
            logger.warning(f"[SIGNAL-TRACKER] Compaction error: {e}")


# ── Singleton ──
_instance: Optional[SignalTracker] = None


def get_signal_tracker() -> SignalTracker:
    global _instance
    if _instance is None:
        _instance = SignalTracker()
    return _instance
