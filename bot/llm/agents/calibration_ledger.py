"""
Agent Calibration Ledger: tracks per-agent, per-regime prediction accuracy.

Each agent's directional predictions are scored against actual outcomes,
broken down by regime. This creates a calibration map:
  "Trade Agent in trend regime: 62% accuracy, +9% overconfident"
  "Critic Agent vetoes in range: 42% accurate (vetoes are HURTING)"

The ledger feeds into dynamic prompt injection — when an agent's accuracy
drops, its prompt gets a calibration prefix telling it to adjust.

Storage: data/llm/agent_calibration.json
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.calibration_ledger")

_CALIBRATION_PATH = os.path.join("data", "llm", "agent_calibration.json")
_MAX_ENTRIES_PER_BUCKET = 100  # Keep last N outcomes per agent+regime


class CalibrationBucket:
    """Tracks outcomes for a specific (agent, regime) pair."""

    def __init__(self):
        self.outcomes: List[Dict[str, Any]] = []  # {correct: bool, confidence: float, ts: float}

    @property
    def accuracy(self) -> float:
        if not self.outcomes:
            return 0.5
        correct = sum(1 for o in self.outcomes if o.get("correct"))
        return correct / len(self.outcomes)

    @property
    def avg_confidence(self) -> float:
        if not self.outcomes:
            return 0.5
        return sum(o.get("confidence", 0.5) for o in self.outcomes) / len(self.outcomes)

    @property
    def brier_score(self) -> float:
        """Brier score: mean squared error of probabilistic predictions.

        Measures both calibration AND sharpness. Lower = better.
        - 0.25 = always predicting 50% (no skill)
        - <0.20 = good calibration
        - <0.10 = excellent calibration
        - 0.0 = perfect (impossible in practice)

        Unlike simple accuracy, Brier score penalizes overconfidence:
        a model that says 90% confident but wins 60% scores worse than
        one that says 60% confident and wins 60%.
        """
        if not self.outcomes:
            return 0.25  # no-skill baseline
        return sum(
            (o.get("confidence", 0.5) - (1.0 if o.get("correct") else 0.0)) ** 2
            for o in self.outcomes
        ) / len(self.outcomes)

    @property
    def calibration_drift(self) -> float:
        """Positive = overconfident, negative = underconfident."""
        return self.avg_confidence - self.accuracy

    @property
    def n(self) -> int:
        return len(self.outcomes)

    def record(self, correct: bool, confidence: float) -> None:
        self.outcomes.append({
            "correct": correct,
            "confidence": round(confidence, 3),
            "ts": time.time(),
        })
        if len(self.outcomes) > _MAX_ENTRIES_PER_BUCKET:
            self.outcomes = self.outcomes[-_MAX_ENTRIES_PER_BUCKET:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 3),
            "avg_confidence": round(self.avg_confidence, 3),
            "calibration_drift": round(self.calibration_drift, 3),
            "brier_score": round(self.brier_score, 4),
            "n": self.n,
            "outcomes": self.outcomes[-50:],  # Save last 50
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationBucket":
        bucket = cls()
        bucket.outcomes = data.get("outcomes", [])
        return bucket


class CalibrationLedger:
    """Per-agent, per-regime calibration tracking."""

    def __init__(self):
        self._buckets: Dict[str, CalibrationBucket] = {}  # key = "agent:regime"
        self._load()

    def _key(self, agent: str, regime: str) -> str:
        return f"{agent}:{regime}"

    def record_outcome(
        self,
        agent: str,
        regime: str,
        correct: bool,
        confidence: float,
    ) -> None:
        """Record a prediction outcome for an agent in a regime."""
        key = self._key(agent, regime)
        if key not in self._buckets:
            self._buckets[key] = CalibrationBucket()
        self._buckets[key].record(correct, confidence)
        self._save()

    def get_calibration(self, agent: str, regime: str) -> Dict[str, Any]:
        """Get calibration stats for agent+regime."""
        key = self._key(agent, regime)
        bucket = self._buckets.get(key)
        if not bucket or bucket.n < 3:
            return {"accuracy": 0.5, "calibration_drift": 0.0, "n": 0, "reliable": False}
        return {
            "accuracy": round(bucket.accuracy, 3),
            "avg_confidence": round(bucket.avg_confidence, 3),
            "calibration_drift": round(bucket.calibration_drift, 3),
            "brier_score": round(bucket.brier_score, 4),
            "n": bucket.n,
            "reliable": bucket.n >= 10,
        }

    def get_agent_summary(self, agent: str) -> Dict[str, Any]:
        """Get calibration summary across all regimes for an agent."""
        prefix = f"{agent}:"
        summary = {}
        total_correct = 0
        total_n = 0
        for key, bucket in self._buckets.items():
            if key.startswith(prefix):
                regime = key[len(prefix):]
                if bucket.n >= 3:
                    summary[regime] = {
                        "acc": round(bucket.accuracy, 2),
                        "cal": round(bucket.calibration_drift, 2),
                        "brier": round(bucket.brier_score, 3),
                        "n": bucket.n,
                    }
                    total_correct += sum(1 for o in bucket.outcomes if o.get("correct"))
                    total_n += bucket.n

        overall_acc = total_correct / max(total_n, 1)
        return {
            "overall_accuracy": round(overall_acc, 3),
            "total_decisions": total_n,
            "per_regime": summary,
        }

    def get_prompt_calibration(self, agent: str, regime: str) -> str:
        """Generate a calibration prefix for dynamic prompt injection.

        Returns empty string if no meaningful calibration data exists.
        """
        cal = self.get_calibration(agent, regime)
        if not cal.get("reliable"):
            return ""

        parts = []
        acc = cal["accuracy"]
        drift = cal["calibration_drift"]
        brier = cal.get("brier_score", 0.25)
        n = cal["n"]

        # Brier score feedback (probabilistic calibration quality)
        if brier > 0.30 and n >= 10:
            parts.append(
                f"POOR CALIBRATION: Your Brier score in {regime} is {brier:.2f} "
                f"(>{0.25} = worse than coin flip). Your confidence values are unreliable. "
                f"Reduce extreme confidence levels — stay closer to 0.50-0.65."
            )
        elif brier < 0.15 and n >= 15:
            parts.append(
                f"EXCELLENT CALIBRATION: Brier={brier:.2f} in {regime}. "
                f"Your probability estimates are well-calibrated."
            )

        # Accuracy warning
        if acc < 0.45 and n >= 15:
            parts.append(
                f"CAUTION: Your {regime} accuracy is {acc:.0%} over {n} decisions. "
                f"Raise your threshold — only proceed if confidence >= 0.70."
            )
        elif acc > 0.65 and n >= 15:
            parts.append(
                f"STRONG: Your {regime} accuracy is {acc:.0%} over {n} decisions. "
                f"Trust your reads in {regime} — don't second-guess."
            )

        # Calibration drift correction
        if drift > 0.12:
            pct = int(drift * 100)
            parts.append(
                f"BIAS: You are +{pct}% overconfident in {regime}. "
                f"Reduce all confidence outputs by {min(pct, 15)}%."
            )
        elif drift < -0.12:
            pct = int(abs(drift) * 100)
            parts.append(
                f"BIAS: You are -{pct}% underconfident in {regime}. "
                f"Increase confidence by {min(pct, 15)}%. You're missing winners."
            )

        return " ".join(parts)

    def get_compact_for_snapshot(self, agent: str) -> Dict[str, Any]:
        """Get compact calibration data to inject into agent's input snapshot."""
        summary = self.get_agent_summary(agent)
        if summary["total_decisions"] < 5:
            return {}
        # Only include regimes with enough data
        compact = {}
        for regime, data in summary.get("per_regime", {}).items():
            if data["n"] >= 5:
                compact[regime] = {
                    "acc": data["acc"], "cal": data["cal"],
                    "brier": data.get("brier", 0.25), "n": data["n"],
                }
        if compact:
            return {"agent_cal": compact, "overall_acc": summary["overall_accuracy"]}
        return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_CALIBRATION_PATH), exist_ok=True)
            data = {key: bucket.to_dict() for key, bucket in self._buckets.items()}
            with open(_CALIBRATION_PATH, "w") as f:
                json.dump(data, f, separators=(",", ":"))
        except Exception as e:
            logger.debug(f"[CALIBRATION] Save failed: {e}")

    def _load(self) -> None:
        if not os.path.exists(_CALIBRATION_PATH):
            return
        try:
            with open(_CALIBRATION_PATH) as f:
                data = json.load(f)
            for key, bucket_data in data.items():
                self._buckets[key] = CalibrationBucket.from_dict(bucket_data)
            logger.debug(f"[CALIBRATION] Loaded {len(self._buckets)} calibration buckets")
        except Exception as e:
            logger.debug(f"[CALIBRATION] Load failed: {e}")


# ── Singleton ────────────────────────────────────────────────────

_ledger: Optional[CalibrationLedger] = None


def get_calibration_ledger() -> CalibrationLedger:
    """Get or create the singleton CalibrationLedger."""
    global _ledger
    if _ledger is None:
        _ledger = CalibrationLedger()
    return _ledger
