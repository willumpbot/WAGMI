"""
Recommendation Engine — Structured suggestion generation & queuing.

The LLM and feedback systems generate recommendations, but they were
previously invisible. This engine:

1. Collects recommendations from ALL sources (feedback loop, self-teaching,
   parameter tuner, evolution tracker, LLM decisions)
2. Scores them by expected impact and confidence
3. Queues them for user review or auto-application (based on trust level)
4. Tracks which recommendations were applied and their outcomes
5. Feeds recommendation accuracy back into trust scoring

Recommendation Types:
    RULE       — New trading rule ("IF funding > 5% THEN reduce leverage")
    PARAMETER  — Parameter change ("Confidence floor 65% → 72%")
    STRATEGY   — Strategy adjustment ("Boost regime_trend weight to 1.3x in trending")
    AVOIDANCE  — Thing to avoid ("Stop trading SOL during low-liquidity hours")
    STRUCTURE  — System-level change ("Add cross-asset correlation tracking")

Usage:
    engine = get_recommendation_engine()
    engine.add_recommendation(
        rec_type=RecType.PARAMETER,
        title="Raise confidence floor for BTC",
        description="BTC trades at 60-65% confidence lose 70% of the time",
        suggested_action="Set BTC confidence floor to 72%",
        source="adaptive_confidence",
        confidence=0.75,
        expected_impact=0.15,
    )
    pending = engine.get_pending()
    engine.apply(rec_id, outcome="applied")
"""

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.growth.recommendations")

_DATA_DIR = os.path.join("data", "llm", "growth")
_RECS_FILE = "recommendations.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


class RecType(str, Enum):
    RULE = "rule"
    PARAMETER = "parameter"
    STRATEGY = "strategy"
    AVOIDANCE = "avoidance"
    STRUCTURE = "structure"


class RecStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"


class RecPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Recommendation:
    """A single structured recommendation."""
    rec_id: str
    rec_type: str
    title: str
    description: str
    suggested_action: str
    source: str                          # Which system generated this
    confidence: float = 0.5              # How confident in the recommendation (0-1)
    expected_impact: float = 0.0         # Expected PnL impact (as fraction)
    priority: str = "medium"
    status: str = "pending"
    created_at: float = 0.0
    applied_at: float = 0.0
    outcome_measured_at: float = 0.0
    outcome_was_positive: Optional[bool] = None
    outcome_notes: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    auto_applicable: bool = False        # Can be auto-applied without user approval
    ttl_hours: float = 48.0              # Expires after this many hours

    @property
    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        return (time.time() - self.created_at) > (self.ttl_hours * 3600)

    @property
    def impact_score(self) -> float:
        """Composite score for prioritization."""
        return self.confidence * (1.0 + abs(self.expected_impact)) * {
            "critical": 4.0, "high": 2.0, "medium": 1.0, "low": 0.5,
        }.get(self.priority, 1.0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recommendation":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class RecommendationEngine:
    """Collects, scores, queues, and tracks recommendations."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._recs: List[Recommendation] = []
        self._outcome_tracker: Dict[str, Dict] = defaultdict(
            lambda: {"total": 0, "positive": 0}
        )
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _RECS_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._recs = [Recommendation.from_dict(r) for r in data.get("recommendations", [])]
                self._outcome_tracker = defaultdict(
                    lambda: {"total": 0, "positive": 0},
                    data.get("outcome_tracker", {}),
                )
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[RECS] Failed to load: {e}")

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _RECS_FILE)
        # Keep last 500 recs
        if len(self._recs) > 500:
            self._recs = sorted(self._recs, key=lambda r: r.created_at, reverse=True)[:500]
        try:
            with open(path, "w") as f:
                json.dump({
                    "recommendations": [r.to_dict() for r in self._recs],
                    "outcome_tracker": dict(self._outcome_tracker),
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[RECS] Failed to save: {e}")

    def add_recommendation(
        self,
        rec_type: str,
        title: str,
        description: str,
        suggested_action: str,
        source: str,
        confidence: float = 0.5,
        expected_impact: float = 0.0,
        priority: str = "medium",
        context: Dict = None,
        tags: List[str] = None,
        auto_applicable: bool = False,
        ttl_hours: float = 48.0,
    ) -> Recommendation:
        """Add a new recommendation to the queue."""
        self._ensure_loaded()

        # Deduplicate: don't add if same title + source exists within last 2 hours
        cutoff = time.time() - 7200
        for r in self._recs:
            if (r.title == title and r.source == source
                    and r.created_at > cutoff and r.status == "pending"):
                logger.debug(f"[RECS] Dedup: {title} from {source}")
                return r

        rec = Recommendation(
            rec_id=f"rec_{uuid.uuid4().hex[:8]}",
            rec_type=rec_type,
            title=title,
            description=description,
            suggested_action=suggested_action,
            source=source,
            confidence=confidence,
            expected_impact=expected_impact,
            priority=priority,
            status="pending",
            created_at=time.time(),
            context=context or {},
            tags=tags or [],
            auto_applicable=auto_applicable,
            ttl_hours=ttl_hours,
        )

        self._recs.append(rec)
        self._save()

        logger.info(
            f"[RECS] New {rec_type} recommendation: {title} "
            f"(conf={confidence:.0%}, impact={expected_impact:+.1%}, "
            f"source={source}, priority={priority})"
        )
        return rec

    def get_pending(self, rec_type: str = None, limit: int = 20) -> List[Recommendation]:
        """Get pending recommendations, sorted by impact score."""
        self._ensure_loaded()
        self._expire_old()
        pending = [
            r for r in self._recs
            if r.status == "pending"
            and (not rec_type or r.rec_type == rec_type)
        ]
        return sorted(pending, key=lambda r: r.impact_score, reverse=True)[:limit]

    def get_auto_applicable(self) -> List[Recommendation]:
        """Get recommendations that can be auto-applied."""
        self._ensure_loaded()
        return [
            r for r in self._recs
            if r.status == "pending" and r.auto_applicable and not r.is_expired
        ]

    def apply(self, rec_id: str, outcome_notes: str = "") -> bool:
        """Mark a recommendation as applied."""
        self._ensure_loaded()
        for r in self._recs:
            if r.rec_id == rec_id:
                r.status = "applied"
                r.applied_at = time.time()
                r.outcome_notes = outcome_notes
                self._save()
                logger.info(f"[RECS] Applied: {r.title} ({r.rec_id})")
                return True
        return False

    def reject(self, rec_id: str, reason: str = "") -> bool:
        """Mark a recommendation as rejected."""
        self._ensure_loaded()
        for r in self._recs:
            if r.rec_id == rec_id:
                r.status = "rejected"
                r.outcome_notes = reason
                self._save()
                logger.info(f"[RECS] Rejected: {r.title} ({r.rec_id})")
                return True
        return False

    def record_outcome(self, rec_id: str, was_positive: bool, notes: str = ""):
        """Record whether an applied recommendation had a positive outcome."""
        self._ensure_loaded()
        for r in self._recs:
            if r.rec_id == rec_id:
                r.outcome_measured_at = time.time()
                r.outcome_was_positive = was_positive
                r.outcome_notes = notes
                r.status = "validated" if was_positive else "invalidated"

                # Update source accuracy tracking
                tracker = self._outcome_tracker[r.source]
                tracker["total"] += 1
                if was_positive:
                    tracker["positive"] += 1

                self._save()
                logger.info(
                    f"[RECS] Outcome for {r.title}: "
                    f"{'POSITIVE' if was_positive else 'NEGATIVE'} — {notes}"
                )
                return
        logger.warning(f"[RECS] rec_id {rec_id} not found for outcome recording")

    def get_source_accuracy(self, source: str) -> float:
        """Get the historical accuracy of recommendations from a source."""
        self._ensure_loaded()
        tracker = self._outcome_tracker.get(source, {})
        total = tracker.get("total", 0)
        if total < 3:
            return 0.5  # Not enough data
        return tracker.get("positive", 0) / total

    def _expire_old(self):
        """Mark expired recommendations."""
        changed = False
        for r in self._recs:
            if r.status == "pending" and r.is_expired:
                r.status = "expired"
                changed = True
        if changed:
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        """Get recommendation engine statistics."""
        self._ensure_loaded()
        by_status = defaultdict(int)
        by_type = defaultdict(int)
        by_source = defaultdict(int)
        for r in self._recs:
            by_status[r.status] += 1
            by_type[r.rec_type] += 1
            by_source[r.source] += 1

        return {
            "total": len(self._recs),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "by_source": dict(by_source),
            "source_accuracy": {
                src: {"total": t["total"], "positive": t["positive"],
                      "accuracy": t["positive"] / t["total"] if t["total"] > 0 else 0}
                for src, t in self._outcome_tracker.items()
            },
        }

    def format_pending_telegram(self, limit: int = 5) -> str:
        """Format pending recommendations for Telegram display."""
        pending = self.get_pending(limit=limit)
        if not pending:
            return "No pending recommendations."

        lines = ["*Pending Recommendations*\n"]
        for i, r in enumerate(pending, 1):
            priority_icon = {
                "critical": "!!", "high": "!", "medium": "-", "low": ".",
            }.get(r.priority, "-")

            lines.append(
                f"{i}. [{priority_icon}] *{r.title}*\n"
                f"   {r.description[:120]}\n"
                f"   Action: {r.suggested_action[:100]}\n"
                f"   Confidence: {r.confidence:.0%} | Source: {r.source}\n"
                f"   ID: `{r.rec_id}`"
            )

        source_acc = []
        for src, tracker in self._outcome_tracker.items():
            if tracker["total"] >= 3:
                acc = tracker["positive"] / tracker["total"]
                source_acc.append(f"{src}: {acc:.0%}")
        if source_acc:
            lines.append(f"\nSource accuracy: {', '.join(source_acc)}")

        return "\n".join(lines)

    def format_for_llm_prompt(self, limit: int = 5) -> str:
        """Format recent recommendations for inclusion in LLM prompt."""
        self._ensure_loaded()
        recent_applied = [
            r for r in self._recs
            if r.status in ("applied", "validated", "invalidated")
        ][-10:]

        if not recent_applied:
            return ""

        lines = ["RECENT RECOMMENDATIONS & OUTCOMES:"]
        for r in recent_applied:
            outcome = "PENDING"
            if r.outcome_was_positive is True:
                outcome = "POSITIVE"
            elif r.outcome_was_positive is False:
                outcome = "NEGATIVE"
            elif r.status == "applied":
                outcome = "AWAITING MEASUREMENT"
            lines.append(f"  [{r.rec_type}] {r.title} -> {outcome}")

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────

_engine: Optional[RecommendationEngine] = None


def get_recommendation_engine() -> RecommendationEngine:
    """Get the singleton RecommendationEngine."""
    global _engine
    if _engine is None:
        _engine = RecommendationEngine()
    return _engine
