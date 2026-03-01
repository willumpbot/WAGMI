"""
Self-Improvement Engine — The Meta-Layer.

This is the crown jewel: the LLM proposes improvements to the SYSTEM ITSELF.

Types of proposals:
1. RULE_PROPOSAL   — New trading rule to codify
2. PARAM_CHANGE    — Specific parameter adjustment with evidence
3. STRATEGY_TWEAK  — Strategy weight or behavior change
4. RISK_ADJUSTMENT — Risk management changes (leverage caps, drawdown limits)
5. ARCHITECTURE    — System-level structural improvement

Safety levels:
    AUTO_SAFE     — Can be applied automatically (low-risk parameter tuning)
    REVIEW_NEEDED — Surfaces to user for review before applying
    CODE_CHANGE   — Generates a description only; human implements

The engine tracks which proposals succeeded vs failed, building a meta-learning
loop: the LLM learns what kinds of improvements actually help.

Usage:
    engine = get_self_improvement_engine()
    engine.propose(
        proposal_type="PARAM_CHANGE",
        title="Raise BTC confidence floor to 72%",
        description="BTC trades at 60-65% confidence lose 70% of the time",
        evidence=["10 trades, 3 wins at 60-65% confidence"],
        suggested_action={"parameter": "confidence_floor.BTC", "old": 65, "new": 72},
        safety_level="AUTO_SAFE",
    )
    auto_proposals = engine.get_auto_applicable()
    engine.apply_proposal(proposal_id, outcome_notes="Applied successfully")
"""

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.growth.self_improvement")

_DATA_DIR = os.path.join("data", "llm", "growth")
_PROPOSALS_FILE = "self_improvement_proposals.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


class ProposalType:
    RULE_PROPOSAL = "rule_proposal"
    PARAM_CHANGE = "param_change"
    STRATEGY_TWEAK = "strategy_tweak"
    RISK_ADJUSTMENT = "risk_adjustment"
    ARCHITECTURE = "architecture"


class SafetyLevel:
    AUTO_SAFE = "auto_safe"           # Low risk, auto-apply
    REVIEW_NEEDED = "review_needed"   # Medium risk, needs human approval
    CODE_CHANGE = "code_change"       # High risk, generates description only


class ProposalStatus:
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    VALIDATED = "validated"       # Applied and confirmed positive
    INVALIDATED = "invalidated"   # Applied but had negative outcome
    EXPIRED = "expired"


@dataclass
class ImprovementProposal:
    """A structured proposal for system improvement."""
    proposal_id: str
    proposal_type: str
    title: str
    description: str
    evidence: List[str] = field(default_factory=list)
    suggested_action: Dict[str, Any] = field(default_factory=dict)
    safety_level: str = "review_needed"
    status: str = "proposed"
    confidence: float = 0.5
    expected_impact: str = ""       # "reduce losses by ~15%", "improve WR by 5%"
    source: str = ""                # "self_teaching", "feedback_loop", "llm_decision"
    created_at: float = 0.0
    applied_at: float = 0.0
    outcome_measured_at: float = 0.0
    outcome_was_positive: Optional[bool] = None
    outcome_notes: str = ""
    trades_before_apply: int = 0
    trades_after_apply: int = 0
    wr_before: float = 0.0
    wr_after: float = 0.0
    pnl_impact: float = 0.0
    ttl_hours: float = 72.0

    @property
    def is_expired(self) -> bool:
        if self.status != "proposed":
            return False
        return (time.time() - self.created_at) > (self.ttl_hours * 3600)

    @property
    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ImprovementProposal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SelfImprovementEngine:
    """Manages system improvement proposals with safety-gated application."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._proposals: List[ImprovementProposal] = []
        self._meta_stats: Dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _PROPOSALS_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._proposals = [
                    ImprovementProposal.from_dict(p)
                    for p in data.get("proposals", [])
                ]
                self._meta_stats = data.get("meta_stats", {})
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[SELF-IMPROVE] Failed to load: {e}")

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _PROPOSALS_FILE)
        if len(self._proposals) > 300:
            self._proposals = sorted(
                self._proposals, key=lambda p: p.created_at, reverse=True
            )[:300]
        try:
            with open(path, "w") as f:
                json.dump({
                    "proposals": [p.to_dict() for p in self._proposals],
                    "meta_stats": self._meta_stats,
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[SELF-IMPROVE] Failed to save: {e}")

    def propose(
        self,
        proposal_type: str,
        title: str,
        description: str,
        evidence: List[str] = None,
        suggested_action: Dict[str, Any] = None,
        safety_level: str = "review_needed",
        confidence: float = 0.5,
        expected_impact: str = "",
        source: str = "system",
    ) -> ImprovementProposal:
        """Submit a new improvement proposal."""
        self._ensure_loaded()

        # Deduplicate
        for p in self._proposals:
            if (p.title == title and p.status == "proposed"
                    and time.time() - p.created_at < 7200):
                return p

        proposal = ImprovementProposal(
            proposal_id=f"imp_{uuid.uuid4().hex[:8]}",
            proposal_type=proposal_type,
            title=title,
            description=description,
            evidence=evidence or [],
            suggested_action=suggested_action or {},
            safety_level=safety_level,
            status="proposed",
            confidence=confidence,
            expected_impact=expected_impact,
            source=source,
            created_at=time.time(),
        )

        self._proposals.append(proposal)
        self._save()

        logger.info(
            f"[SELF-IMPROVE] New proposal [{proposal_type}]: {title} "
            f"(safety={safety_level}, conf={confidence:.0%}, source={source})"
        )
        return proposal

    def get_auto_applicable(self) -> List[ImprovementProposal]:
        """Get proposals that can be auto-applied (AUTO_SAFE level)."""
        self._ensure_loaded()
        self._expire_old()
        return [
            p for p in self._proposals
            if p.status == "proposed"
            and p.safety_level == SafetyLevel.AUTO_SAFE
            and not p.is_expired
        ]

    def get_pending_review(self) -> List[ImprovementProposal]:
        """Get proposals that need human review."""
        self._ensure_loaded()
        self._expire_old()
        return [
            p for p in self._proposals
            if p.status == "proposed"
            and p.safety_level in (SafetyLevel.REVIEW_NEEDED, SafetyLevel.CODE_CHANGE)
            and not p.is_expired
        ]

    def approve_proposal(self, proposal_id: str) -> bool:
        """Approve a proposal for application."""
        self._ensure_loaded()
        for p in self._proposals:
            if p.proposal_id == proposal_id and p.status == "proposed":
                p.status = "approved"
                self._save()
                logger.info(f"[SELF-IMPROVE] Approved: {p.title}")
                return True
        return False

    def apply_proposal(
        self,
        proposal_id: str,
        outcome_notes: str = "",
        trades_at_apply: int = 0,
        current_wr: float = 0.0,
    ) -> bool:
        """Mark a proposal as applied."""
        self._ensure_loaded()
        for p in self._proposals:
            if p.proposal_id == proposal_id and p.status in ("proposed", "approved"):
                p.status = "applied"
                p.applied_at = time.time()
                p.outcome_notes = outcome_notes
                p.trades_before_apply = trades_at_apply
                p.wr_before = current_wr
                self._save()
                logger.info(f"[SELF-IMPROVE] Applied: {p.title}")
                return True
        return False

    def reject_proposal(self, proposal_id: str, reason: str = "") -> bool:
        """Reject a proposal."""
        self._ensure_loaded()
        for p in self._proposals:
            if p.proposal_id == proposal_id and p.status in ("proposed", "approved"):
                p.status = "rejected"
                p.outcome_notes = reason
                self._save()
                logger.info(f"[SELF-IMPROVE] Rejected: {p.title} -- {reason}")
                return True
        return False

    def record_outcome(
        self,
        proposal_id: str,
        was_positive: bool,
        notes: str = "",
        trades_after: int = 0,
        wr_after: float = 0.0,
        pnl_impact: float = 0.0,
    ):
        """Record whether an applied proposal had a positive outcome."""
        self._ensure_loaded()
        for p in self._proposals:
            if p.proposal_id == proposal_id and p.status == "applied":
                p.outcome_measured_at = time.time()
                p.outcome_was_positive = was_positive
                p.outcome_notes = notes
                p.trades_after_apply = trades_after
                p.wr_after = wr_after
                p.pnl_impact = pnl_impact
                p.status = "validated" if was_positive else "invalidated"

                # Update meta-stats
                source = p.source
                if source not in self._meta_stats:
                    self._meta_stats[source] = {
                        "total": 0, "positive": 0, "negative": 0
                    }
                self._meta_stats[source]["total"] += 1
                if was_positive:
                    self._meta_stats[source]["positive"] += 1
                else:
                    self._meta_stats[source]["negative"] += 1

                self._save()
                logger.info(
                    f"[SELF-IMPROVE] Outcome for '{p.title}': "
                    f"{'POSITIVE' if was_positive else 'NEGATIVE'} — {notes}"
                )
                return

    def generate_proposals_from_performance(
        self,
        recent_trades: List[Dict[str, Any]],
        current_config: Dict[str, Any] = None,
    ) -> List[ImprovementProposal]:
        """Auto-generate proposals from recent performance data.

        This is the core self-improvement logic: analyze performance
        patterns and propose concrete changes.
        """
        self._ensure_loaded()
        proposals = []

        if len(recent_trades) < 10:
            return proposals

        # Analysis: overall performance
        wins = sum(1 for t in recent_trades if t.get("outcome") == "WIN")
        total = len(recent_trades)
        wr = wins / total if total > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in recent_trades)

        # Proposal 1: Confidence floor adjustment
        low_conf_trades = [t for t in recent_trades if t.get("confidence", 100) < 70]
        if len(low_conf_trades) >= 5:
            low_conf_wins = sum(1 for t in low_conf_trades if t.get("outcome") == "WIN")
            low_conf_wr = low_conf_wins / len(low_conf_trades)
            if low_conf_wr < 0.4:
                p = self.propose(
                    proposal_type=ProposalType.PARAM_CHANGE,
                    title="Raise confidence floor — low-conf trades losing",
                    description=(
                        f"Trades below 70% confidence: {low_conf_wr:.0%} WR "
                        f"over {len(low_conf_trades)} trades. "
                        f"Raising floor would filter these losses."
                    ),
                    evidence=[
                        f"{low_conf_wins}/{len(low_conf_trades)} wins at <70% confidence",
                        f"Overall WR: {wr:.0%} over {total} trades",
                    ],
                    suggested_action={
                        "parameter": "confidence_floor",
                        "current": 65,
                        "proposed": 72,
                    },
                    safety_level=SafetyLevel.AUTO_SAFE,
                    confidence=0.7,
                    expected_impact=f"Filter ~{len(low_conf_trades)} losing trades",
                    source="self_improvement",
                )
                proposals.append(p)

        # Proposal 2: Leverage reduction if high-leverage trades losing
        high_lev_trades = [t for t in recent_trades if t.get("leverage", 1) >= 5]
        if len(high_lev_trades) >= 5:
            high_lev_wins = sum(1 for t in high_lev_trades if t.get("outcome") == "WIN")
            high_lev_wr = high_lev_wins / len(high_lev_trades)
            high_lev_pnl = sum(t.get("pnl", 0) for t in high_lev_trades)
            if high_lev_wr < 0.45 and high_lev_pnl < 0:
                p = self.propose(
                    proposal_type=ProposalType.RISK_ADJUSTMENT,
                    title="Reduce max leverage — high-leverage trades underperforming",
                    description=(
                        f"5x+ leverage trades: {high_lev_wr:.0%} WR, "
                        f"PnL=${high_lev_pnl:+.2f} over {len(high_lev_trades)} trades"
                    ),
                    evidence=[
                        f"{high_lev_wins}/{len(high_lev_trades)} wins at 5x+ leverage",
                        f"Total PnL from high-lev: ${high_lev_pnl:+.2f}",
                    ],
                    suggested_action={
                        "parameter": "max_leverage",
                        "current": 10,
                        "proposed": 5,
                    },
                    safety_level=SafetyLevel.REVIEW_NEEDED,
                    confidence=0.6,
                    expected_impact=f"Reduce high-leverage losses (~${abs(high_lev_pnl):.0f})",
                    source="self_improvement",
                )
                proposals.append(p)

        # Proposal 3: Symbol-specific avoidance
        by_symbol = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in recent_trades:
            sym = t.get("symbol", "")
            by_symbol[sym]["total"] += 1
            if t.get("outcome") == "WIN":
                by_symbol[sym]["wins"] += 1
            by_symbol[sym]["pnl"] += t.get("pnl", 0)

        for sym, stats in by_symbol.items():
            if stats["total"] >= 5 and stats["pnl"] < 0:
                sym_wr = stats["wins"] / stats["total"]
                if sym_wr < 0.3:
                    p = self.propose(
                        proposal_type=ProposalType.STRATEGY_TWEAK,
                        title=f"Consider pausing {sym} — consistent losses",
                        description=(
                            f"{sym}: {sym_wr:.0%} WR, PnL=${stats['pnl']:+.2f} "
                            f"over {stats['total']} trades"
                        ),
                        evidence=[
                            f"{stats['wins']}/{stats['total']} wins for {sym}",
                            f"PnL: ${stats['pnl']:+.2f}",
                        ],
                        suggested_action={
                            "action": "pause_symbol",
                            "symbol": sym,
                            "duration_hours": 24,
                        },
                        safety_level=SafetyLevel.REVIEW_NEEDED,
                        confidence=0.65,
                        expected_impact=f"Avoid ~${abs(stats['pnl']):.0f} in losses",
                        source="self_improvement",
                    )
                    proposals.append(p)

        # Proposal 4: Strategy weight adjustment
        by_strategy = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in recent_trades:
            strat = t.get("strategy", "")
            by_strategy[strat]["total"] += 1
            if t.get("outcome") == "WIN":
                by_strategy[strat]["wins"] += 1
            by_strategy[strat]["pnl"] += t.get("pnl", 0)

        for strat, stats in by_strategy.items():
            if stats["total"] >= 8:
                strat_wr = stats["wins"] / stats["total"]
                if strat_wr >= 0.65 and stats["pnl"] > 0:
                    p = self.propose(
                        proposal_type=ProposalType.STRATEGY_TWEAK,
                        title=f"Boost {strat} weight — outperforming",
                        description=(
                            f"{strat}: {strat_wr:.0%} WR, PnL=${stats['pnl']:+.2f} "
                            f"over {stats['total']} trades"
                        ),
                        evidence=[
                            f"{stats['wins']}/{stats['total']} wins",
                            f"PnL: ${stats['pnl']:+.2f}",
                        ],
                        suggested_action={
                            "action": "adjust_weight",
                            "strategy": strat,
                            "weight_multiplier": 1.3,
                        },
                        safety_level=SafetyLevel.AUTO_SAFE,
                        confidence=min(0.8, strat_wr),
                        expected_impact=f"More {strat} trades ({strat_wr:.0%} WR)",
                        source="self_improvement",
                    )
                    proposals.append(p)

        return proposals

    def _expire_old(self):
        """Expire stale proposals."""
        changed = False
        for p in self._proposals:
            if p.status == "proposed" and p.is_expired:
                p.status = "expired"
                changed = True
        if changed:
            self._save()

    def get_source_effectiveness(self) -> Dict[str, Dict[str, Any]]:
        """Meta-learning: which proposal sources produce the best improvements?"""
        self._ensure_loaded()
        result = {}
        for source, stats in self._meta_stats.items():
            total = stats.get("total", 0)
            positive = stats.get("positive", 0)
            result[source] = {
                "total": total,
                "positive": positive,
                "accuracy": positive / total if total > 0 else 0.0,
            }
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive improvement engine statistics."""
        self._ensure_loaded()
        by_status = defaultdict(int)
        by_type = defaultdict(int)
        for p in self._proposals:
            by_status[p.status] += 1
            by_type[p.proposal_type] += 1

        return {
            "total_proposals": len(self._proposals),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "source_effectiveness": self.get_source_effectiveness(),
        }

    def format_telegram(self, limit: int = 5) -> str:
        """Format proposals for Telegram display."""
        self._ensure_loaded()
        pending = self.get_pending_review()
        auto = self.get_auto_applicable()

        lines = ["*Self-Improvement Engine*\n"]

        if auto:
            lines.append(f"*Auto-applicable ({len(auto)}):*")
            for p in auto[:3]:
                lines.append(f"  [AUTO] {p.title} (conf={p.confidence:.0%})")

        if pending:
            lines.append(f"\n*Pending review ({len(pending)}):*")
            for p in pending[:limit]:
                lines.append(
                    f"  [{p.proposal_type}] {p.title}\n"
                    f"    {p.description[:100]}\n"
                    f"    Impact: {p.expected_impact}\n"
                    f"    ID: `{p.proposal_id}`"
                )

        # Meta-learning: source effectiveness
        effectiveness = self.get_source_effectiveness()
        if effectiveness:
            lines.append("\n*Source effectiveness:*")
            for src, data in effectiveness.items():
                if data["total"] >= 3:
                    lines.append(
                        f"  {src}: {data['accuracy']:.0%} "
                        f"({data['positive']}/{data['total']})"
                    )

        if not auto and not pending:
            lines.append("No pending proposals.")

        return "\n".join(lines)

    def format_for_llm_prompt(self) -> str:
        """Format for LLM prompt injection."""
        self._ensure_loaded()
        lines = []

        # Recent outcomes
        recent = [
            p for p in self._proposals
            if p.status in ("validated", "invalidated")
        ][-5:]
        if recent:
            lines.append("RECENT IMPROVEMENT OUTCOMES:")
            for p in recent:
                result = "HELPED" if p.outcome_was_positive else "HURT"
                lines.append(f"  [{p.proposal_type}] {p.title} -> {result}")

        # Pending proposals
        pending = [p for p in self._proposals if p.status == "proposed"][:3]
        if pending:
            lines.append("PENDING PROPOSALS:")
            for p in pending:
                lines.append(f"  [{p.safety_level}] {p.title} (conf={p.confidence:.0%})")

        return "\n".join(lines) if lines else ""


# ── Singleton ─────────────────────────────────────────────

_engine: Optional[SelfImprovementEngine] = None


def get_self_improvement_engine() -> SelfImprovementEngine:
    """Get the singleton SelfImprovementEngine."""
    global _engine
    if _engine is None:
        _engine = SelfImprovementEngine()
    return _engine
