"""
Hypothesis Tracker — Visible lifecycle management for trading hypotheses.

Previously, hypotheses existed in the knowledge base but were invisible to the
user and had minimal validation logic. This module provides:

1. Structured hypothesis creation with clear test criteria
2. Automated evidence collection (supporting + contradicting)
3. Confidence progression (grows/shrinks with evidence)
4. Lifecycle stages: PROPOSED → TESTING → VALIDATED → CODIFIED / INVALIDATED
5. User-visible dashboard of active hypotheses
6. Graduation: validated hypotheses become RULES or PRINCIPLES

Usage:
    tracker = get_hypothesis_tracker()
    h = tracker.propose(
        hypothesis="SOL performs better in Asian trading hours (00:00-08:00 UTC)",
        test_criteria="Compare SOL WR in 00-08 UTC vs other hours over 30+ trades",
        category="timing",
        tags=["SOL", "timing"],
    )
    tracker.add_evidence(h.hypothesis_id, supporting=True,
                         evidence="SOL 4/5 wins in Asian hours this week")
    tracker.check_graduation()
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.growth.hypothesis_tracker")

_DATA_DIR = os.path.join("data", "llm", "growth")
_HYPO_FILE = "hypotheses.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


class HypothesisStage(str, Enum):
    PROPOSED = "proposed"
    TESTING = "testing"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"
    CODIFIED = "codified"       # Graduated to a rule/principle


@dataclass
class EvidenceEntry:
    """A single piece of evidence for or against a hypothesis."""
    timestamp: float
    supporting: bool            # True = supports, False = contradicts
    description: str
    source: str = ""            # "trade_outcome", "backtest", "llm_observation"
    strength: float = 1.0       # How strong is this evidence? (0.5-2.0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Hypothesis:
    """A structured, trackable hypothesis."""
    hypothesis_id: str
    statement: str              # The hypothesis itself
    test_criteria: str          # How to test it
    category: str               # "timing", "regime", "symbol", "strategy", "risk"
    stage: str = "proposed"
    confidence: float = 0.5     # 0.0 = definitely false, 1.0 = definitely true
    created_at: float = 0.0
    last_updated: float = 0.0
    proposed_by: str = ""       # "llm", "self_teaching", "feedback_loop"
    evidence: List[Dict] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    graduation_target: str = "" # "rule", "principle", "anti_pattern"
    graduated_to: str = ""      # What it became after graduation

    @property
    def supporting_count(self) -> int:
        return sum(1 for e in self.evidence if e.get("supporting", False))

    @property
    def contradicting_count(self) -> int:
        return sum(1 for e in self.evidence if not e.get("supporting", True))

    @property
    def total_evidence(self) -> int:
        return len(self.evidence)

    @property
    def evidence_ratio(self) -> float:
        """Ratio of supporting to total evidence."""
        if not self.evidence:
            return 0.5
        return self.supporting_count / len(self.evidence)

    @property
    def is_ready_for_graduation(self) -> bool:
        """Has enough evidence to graduate to a rule/principle.

        Standard path: 10+ evidence, ratio >= 0.7 or <= 0.3
        Fast-track path: 7+ evidence, ratio >= 0.85 or <= 0.15
        """
        if self.stage != "testing":
            return False
        # Fast-track: strong signal with fewer data points
        if (
            self.total_evidence >= 7
            and (self.evidence_ratio >= 0.85 or self.evidence_ratio <= 0.15)
        ):
            return True
        # Standard path
        return (
            self.total_evidence >= 10
            and (self.evidence_ratio >= 0.7 or self.evidence_ratio <= 0.3)
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Hypothesis":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class HypothesisTracker:
    """Manages the full lifecycle of trading hypotheses."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._hypotheses: List[Hypothesis] = []
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _HYPO_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._hypotheses = [Hypothesis.from_dict(h) for h in data.get("hypotheses", [])]
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[HYPO] Failed to load: {e}")

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _HYPO_FILE)
        if len(self._hypotheses) > 200:
            # Keep active + recent
            active = [h for h in self._hypotheses if h.stage in ("proposed", "testing")]
            graduated = sorted(
                [h for h in self._hypotheses if h.stage in ("validated", "codified", "invalidated")],
                key=lambda h: h.last_updated, reverse=True
            )[:100]
            self._hypotheses = active + graduated
        try:
            with open(path, "w") as f:
                json.dump({
                    "hypotheses": [h.to_dict() for h in self._hypotheses],
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[HYPO] Failed to save: {e}")

    def propose(
        self,
        statement: str,
        test_criteria: str,
        category: str = "general",
        tags: List[str] = None,
        proposed_by: str = "system",
        graduation_target: str = "principle",
    ) -> Hypothesis:
        """Propose a new hypothesis for testing."""
        self._ensure_loaded()

        # Deduplicate
        for h in self._hypotheses:
            if h.statement.lower().strip() == statement.lower().strip():
                logger.debug(f"[HYPO] Dedup: {statement[:50]}")
                return h

        hypo = Hypothesis(
            hypothesis_id=f"hypo_{int(time.time())}_{len(self._hypotheses)}",
            statement=statement,
            test_criteria=test_criteria,
            category=category,
            stage="proposed",
            confidence=0.5,
            created_at=time.time(),
            last_updated=time.time(),
            proposed_by=proposed_by,
            tags=tags or [],
            graduation_target=graduation_target,
        )

        self._hypotheses.append(hypo)
        self._save()

        logger.info(f"[HYPO] Proposed: {statement[:80]} (by {proposed_by})")
        return hypo

    def start_testing(self, hypothesis_id: str) -> bool:
        """Move a hypothesis from proposed to testing."""
        self._ensure_loaded()
        for h in self._hypotheses:
            if h.hypothesis_id == hypothesis_id and h.stage == "proposed":
                h.stage = "testing"
                h.last_updated = time.time()
                self._save()
                logger.info(f"[HYPO] Now testing: {h.statement[:60]}")
                return True
        return False

    def add_evidence(
        self,
        hypothesis_id: str,
        supporting: bool,
        description: str,
        source: str = "trade_outcome",
        strength: float = 1.0,
    ) -> bool:
        """Add evidence for or against a hypothesis."""
        self._ensure_loaded()
        for h in self._hypotheses:
            if h.hypothesis_id == hypothesis_id:
                # Auto-start testing on first evidence
                if h.stage == "proposed":
                    h.stage = "testing"

                entry = EvidenceEntry(
                    timestamp=time.time(),
                    supporting=supporting,
                    description=description[:200],
                    source=source,
                    strength=strength,
                )
                h.evidence.append(entry.to_dict())

                # Keep evidence manageable
                if len(h.evidence) > 50:
                    h.evidence = h.evidence[-50:]

                # Update confidence
                ratio = h.evidence_ratio
                # Weighted: more evidence = more confidence in direction
                data_weight = min(1.0, h.total_evidence / 20)
                h.confidence = 0.5 + (ratio - 0.5) * data_weight

                h.last_updated = time.time()
                self._save()

                direction = "FOR" if supporting else "AGAINST"
                logger.debug(
                    f"[HYPO] Evidence {direction}: {h.statement[:40]} "
                    f"(now {h.supporting_count}:{h.contradicting_count}, "
                    f"conf={h.confidence:.0%})"
                )
                return True
        return False

    def add_evidence_by_trade(self, trade_data: Dict[str, Any]):
        """Automatically add evidence to relevant hypotheses based on a trade outcome.

        Examines each active hypothesis and checks if this trade
        provides supporting or contradicting evidence.
        """
        self._ensure_loaded()
        symbol = trade_data.get("symbol", "")
        regime = trade_data.get("regime", "")
        side = trade_data.get("side", "")
        won = trade_data.get("outcome") == "WIN"
        hour = trade_data.get("hour", -1)
        confidence = trade_data.get("confidence", 0)
        num_agree = trade_data.get("num_agree", 0)

        for h in self._hypotheses:
            if h.stage not in ("proposed", "testing"):
                continue

            statement_lower = h.statement.lower()
            is_relevant = False
            is_supporting = None

            # Symbol-specific hypotheses
            if symbol.lower() in statement_lower:
                is_relevant = True
                if "performs better" in statement_lower or "strong" in statement_lower:
                    is_supporting = won
                elif "performs poorly" in statement_lower or "weak" in statement_lower:
                    is_supporting = not won

            # Regime-specific
            if regime.lower() in statement_lower:
                is_relevant = True
                if "works well" in statement_lower or "profitable" in statement_lower:
                    is_supporting = won
                elif "struggles" in statement_lower or "losing" in statement_lower:
                    is_supporting = not won

            # Side-specific
            if ("longs" in statement_lower or "long" in statement_lower) and side.upper() in ("LONG", "BUY"):
                is_relevant = True
                if "favors" in statement_lower:
                    is_supporting = won
            if ("shorts" in statement_lower or "short" in statement_lower) and side.upper() in ("SHORT", "SELL"):
                is_relevant = True
                if "favors" in statement_lower:
                    is_supporting = won

            # Timing hypotheses
            if "hour" in statement_lower or "session" in statement_lower:
                if "asian" in statement_lower and 0 <= hour <= 8:
                    is_relevant = True
                    is_supporting = won
                elif "london" in statement_lower and 8 <= hour <= 16:
                    is_relevant = True
                    is_supporting = won
                elif "new york" in statement_lower and 13 <= hour <= 21:
                    is_relevant = True
                    is_supporting = won

            if is_relevant and is_supporting is not None:
                self.add_evidence(
                    h.hypothesis_id,
                    supporting=is_supporting,
                    description=(
                        f"{symbol} {side} in {regime}: "
                        f"{'WIN' if won else 'LOSS'} at {confidence:.0f}% conf"
                    ),
                    source="trade_outcome",
                )

    def check_graduation(self) -> List[Hypothesis]:
        """Check all hypotheses for graduation readiness.

        Returns list of hypotheses that graduated.
        """
        self._ensure_loaded()
        graduated = []

        for h in self._hypotheses:
            if not h.is_ready_for_graduation:
                continue

            is_fast_track = (
                h.total_evidence < 10
                and h.total_evidence >= 7
                and (h.evidence_ratio >= 0.85 or h.evidence_ratio <= 0.15)
            )

            if h.evidence_ratio >= 0.7:
                # Validated — graduate to principle/rule
                h.stage = "validated"
                h.graduated_to = h.graduation_target or "principle"
                graduated.append(h)
                if is_fast_track:
                    logger.info(
                        f"[HYPO] FAST-TRACK GRADUATED (validated): {h.statement[:60]} "
                        f"-> {h.graduated_to} ({h.supporting_count}:{h.contradicting_count}, "
                        f"ratio={h.evidence_ratio:.0%})"
                    )
                else:
                    logger.info(
                        f"[HYPO] GRADUATED (validated): {h.statement[:60]} "
                        f"-> {h.graduated_to} ({h.supporting_count}:{h.contradicting_count})"
                    )
            elif h.evidence_ratio <= 0.3:
                # Invalidated
                h.stage = "invalidated"
                h.graduated_to = "anti_pattern"
                graduated.append(h)
                if is_fast_track:
                    logger.info(
                        f"[HYPO] FAST-TRACK INVALIDATED: {h.statement[:60]} "
                        f"({h.supporting_count}:{h.contradicting_count}, "
                        f"ratio={h.evidence_ratio:.0%})"
                    )
                else:
                    logger.info(
                        f"[HYPO] INVALIDATED: {h.statement[:60]} "
                        f"({h.supporting_count}:{h.contradicting_count})"
                    )

            h.last_updated = time.time()

        if graduated:
            self._save()
        return graduated

    def get_active(self) -> List[Hypothesis]:
        """Get all active (proposed + testing) hypotheses."""
        self._ensure_loaded()
        return [h for h in self._hypotheses if h.stage in ("proposed", "testing")]

    def get_graduated(self, limit: int = 20) -> List[Hypothesis]:
        """Get recently graduated hypotheses."""
        self._ensure_loaded()
        grad = [h for h in self._hypotheses if h.stage in ("validated", "invalidated", "codified")]
        return sorted(grad, key=lambda h: h.last_updated, reverse=True)[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get hypothesis tracker statistics."""
        self._ensure_loaded()
        by_stage = defaultdict(int)
        by_category = defaultdict(int)
        for h in self._hypotheses:
            by_stage[h.stage] += 1
            by_category[h.category] += 1

        return {
            "total": len(self._hypotheses),
            "by_stage": dict(by_stage),
            "by_category": dict(by_category),
            "avg_evidence_count": (
                sum(h.total_evidence for h in self._hypotheses) / len(self._hypotheses)
                if self._hypotheses else 0
            ),
        }

    def format_telegram(self) -> str:
        """Format hypothesis dashboard for Telegram."""
        self._ensure_loaded()
        active = self.get_active()
        recent_grad = self.get_graduated(limit=5)

        lines = ["*Hypothesis Dashboard*\n"]

        if active:
            lines.append(f"*Active ({len(active)}):*")
            for h in sorted(active, key=lambda h: h.total_evidence, reverse=True)[:10]:
                stage_icon = "?" if h.stage == "proposed" else "~"
                direction = "+" if h.confidence > 0.55 else ("-" if h.confidence < 0.45 else "=")
                lines.append(
                    f"  [{stage_icon}] {h.statement[:70]}\n"
                    f"      Evidence: {h.supporting_count}:{h.contradicting_count} "
                    f"[{direction}] conf={h.confidence:.0%}"
                )
        else:
            lines.append("No active hypotheses.")

        if recent_grad:
            lines.append(f"\n*Recently Graduated ({len(recent_grad)}):*")
            for h in recent_grad:
                icon = "Y" if h.stage == "validated" else "X"
                lines.append(
                    f"  [{icon}] {h.statement[:60]} -> {h.graduated_to}"
                )

        return "\n".join(lines)

    def format_for_llm_prompt(self) -> str:
        """Format active hypotheses for LLM prompt injection."""
        self._ensure_loaded()
        active = self.get_active()[:8]
        if not active:
            return ""

        lines = ["ACTIVE HYPOTHESES BEING TESTED:"]
        for h in active:
            conf_dir = "likely true" if h.confidence > 0.6 else (
                "likely false" if h.confidence < 0.4 else "undetermined"
            )
            lines.append(
                f"  [{h.category}] {h.statement} "
                f"({h.supporting_count} for, {h.contradicting_count} against = {conf_dir})"
            )

        recent_grad = self.get_graduated(limit=3)
        if recent_grad:
            lines.append("RECENTLY GRADUATED:")
            for h in recent_grad:
                result = "VALIDATED" if h.stage == "validated" else "INVALIDATED"
                lines.append(f"  [{result}] {h.statement}")

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────

_tracker: Optional[HypothesisTracker] = None


def get_hypothesis_tracker() -> HypothesisTracker:
    """Get the singleton HypothesisTracker."""
    global _tracker
    if _tracker is None:
        _tracker = HypothesisTracker()
    return _tracker
