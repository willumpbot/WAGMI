"""
Decision Ledger: Systematic tracking of all theses and outcomes.

Every trade decision is logged with:
- Thesis (directional prediction)
- Confidence decomposition (direction conf, setup conf, timing conf)
- Setup type and regime
- Market context at entry
- Outcome (direction correct, magnitude, timing)

This enables:
1. Systematic thesis accuracy measurement
2. Per-agent accuracy calibration
3. Setup type profitability analysis
4. Regime-specific agent performance
5. Historical pattern validation

The ledger is the "feedback backbone" of the system — it's how we learn.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("bot.llm.agents.decision_ledger")


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DecisionThesis:
    """A thesis is a directional prediction with confidence components."""
    text: str  # "SOL likely +3-4% next 6h because..."
    direction: str  # "long" | "short"
    target: Optional[float] = None  # Expected price
    duration_hours: Optional[int] = None  # How long until target

    # Confidence decomposition (sum should ≈ overall confidence)
    direction_confidence: float = 0.0  # Do we know the direction?
    setup_confidence: float = 0.0  # Is the setup real?
    timing_confidence: float = 0.0  # Is the timing right?

    def overall_confidence(self) -> float:
        """Average of three components."""
        return (self.direction_confidence + self.setup_confidence + self.timing_confidence) / 3.0


@dataclass
class DecisionOutcome:
    """What actually happened (populated after trade closes)."""
    direction_correct: bool  # Did price go the way we predicted?
    magnitude: float  # Actual % move
    timing_hours: float  # How long until peak/trough

    pnl: float  # Actual trade P&L
    pnl_pct: float  # % return on entry

    exit_reason: str  # "TP1" | "SL" | "TRAILING" | "FORCED"
    duration_hours: float  # How long we held

    # Funding impact
    funding_paid: float  # Actual funding costs

    # Was the thesis valid? (Even if trade lost, thesis might have been correct.)
    thesis_validity: str  # "correct" | "wrong_direction" | "wrong_timing" | "wrong_magnitude"


@dataclass
class DecisionRecord:
    """A complete trade decision record: entry through outcome."""
    decision_id: str  # UUID or timestamp-based
    timestamp_entry: datetime

    # What we decided
    symbol: str
    side: str  # "BUY" | "SELL"
    confidence: float  # Overall confidence 0-1
    thesis: DecisionThesis

    # Market context at entry
    regime: str  # "trend" | "range" | "panic" etc.
    setup_type: str  # "trend_at_zone" | "convergent_confluence" etc.
    confluence: int  # How many strategies agreed? (0-11)

    # Which agent made this decision?
    agent: str  # "trade" | "scout" | etc.

    # What gates did it pass?
    gates_passed: Dict[str, bool] = field(default_factory=dict)  # {"rr": true, "ev": true, ...}

    # Why did we make this decision?
    reasoning: str = ""  # Brief summary

    # Was it executed?
    executed: bool = False
    execution_price: Optional[float] = None
    entry_time: Optional[datetime] = None

    # Trade outcome (populated at close)
    outcome: Optional[DecisionOutcome] = None

    # Lessons extracted
    lessons: List[str] = field(default_factory=list)

    # How did this decision perform relative to agent calibration?
    calibration_error: Optional[float] = None  # confidence - actual_win_rate

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        d = asdict(self)
        # Convert datetime to ISO format
        d["timestamp_entry"] = self.timestamp_entry.isoformat()
        if self.entry_time:
            d["entry_time"] = self.entry_time.isoformat()
        # Serialize thesis
        d["thesis"] = asdict(self.thesis)
        # Serialize outcome
        if self.outcome:
            d["outcome"] = asdict(self.outcome)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DecisionRecord":
        """Deserialize from dict."""
        # Parse datetime strings
        d["timestamp_entry"] = datetime.fromisoformat(d["timestamp_entry"])
        if d.get("entry_time"):
            d["entry_time"] = datetime.fromisoformat(d["entry_time"])

        # Parse thesis
        thesis_dict = d["thesis"]
        d["thesis"] = DecisionThesis(**thesis_dict)

        # Parse outcome
        if d.get("outcome"):
            outcome_dict = d["outcome"]
            d["outcome"] = DecisionOutcome(**outcome_dict)

        return DecisionRecord(**d)


# ─────────────────────────────────────────────────────────────────────────────
# DECISION LEDGER (in-memory + file-backed)
# ─────────────────────────────────────────────────────────────────────────────

class DecisionLedger:
    """Tracks all trading decisions and their outcomes."""

    def __init__(self, ledger_path: Optional[Path] = None):
        """Initialize the ledger.

        Args:
            ledger_path: Path to decision ledger JSON file. If None, uses default.
        """
        self.ledger_path = ledger_path or Path(__file__).parent.parent / "data" / "decision_ledger.jsonl"
        self.records: List[DecisionRecord] = []
        self._load()

    def _load(self) -> None:
        """Load existing records from disk."""
        if not self.ledger_path.exists():
            logger.info(f"[DECISION_LEDGER] Creating new ledger at {self.ledger_path}")
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            return

        try:
            with open(self.ledger_path, "r") as f:
                for line in f:
                    if line.strip():
                        record_dict = json.loads(line)
                        record = DecisionRecord.from_dict(record_dict)
                        self.records.append(record)
            logger.info(f"[DECISION_LEDGER] Loaded {len(self.records)} records")
        except Exception as e:
            logger.error(f"[DECISION_LEDGER] Failed to load: {e}")

    def record_decision(
        self,
        symbol: str,
        side: str,
        confidence: float,
        thesis: DecisionThesis,
        regime: str,
        setup_type: str,
        confluence: int,
        agent: str,
        reasoning: str = "",
        gates: Optional[Dict[str, bool]] = None,
    ) -> DecisionRecord:
        """Record a new trade decision.

        Returns: The recorded DecisionRecord
        """
        decision_id = f"{datetime.now().isoformat()}"

        record = DecisionRecord(
            decision_id=decision_id,
            timestamp_entry=datetime.now(),
            symbol=symbol,
            side=side,
            confidence=confidence,
            thesis=thesis,
            regime=regime,
            setup_type=setup_type,
            confluence=confluence,
            agent=agent,
            reasoning=reasoning,
            gates_passed=gates or {},
        )

        self.records.append(record)
        self._persist(record)

        logger.info(f"[DECISION_LEDGER] Recorded: {symbol} {side} @ {confidence:.2f} ({setup_type})")

        return record

    def record_execution(
        self,
        decision_id: str,
        execution_price: float,
    ) -> None:
        """Record that a decision was actually executed."""
        for record in self.records:
            if record.decision_id == decision_id:
                record.executed = True
                record.execution_price = execution_price
                record.entry_time = datetime.now()
                self._persist(record)
                logger.info(f"[DECISION_LEDGER] Executed: {record.symbol} @ {execution_price}")
                return
        logger.warning(f"[DECISION_LEDGER] Decision not found: {decision_id}")

    def record_outcome(
        self,
        decision_id: str,
        outcome: DecisionOutcome,
        lessons: Optional[List[str]] = None,
    ) -> None:
        """Record the outcome of a closed trade."""
        for record in self.records:
            if record.decision_id == decision_id:
                record.outcome = outcome
                record.lessons = lessons or []

                # Calculate calibration error
                actual_wr = 1.0 if outcome.direction_correct else 0.0
                record.calibration_error = record.confidence - actual_wr

                self._persist(record)
                logger.info(f"[DECISION_LEDGER] Outcome: {record.symbol} → {outcome.pnl_pct:+.1%} (thesis: {outcome.thesis_validity})")
                return
        logger.warning(f"[DECISION_LEDGER] Decision not found for outcome: {decision_id}")

    def _persist(self, record: DecisionRecord) -> None:
        """Write a record to disk (append-only)."""
        try:
            with open(self.ledger_path, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"[DECISION_LEDGER] Failed to persist: {e}")

    # ───────────────────────────────────────────────────────────────────────
    # ANALYSIS METHODS
    # ───────────────────────────────────────────────────────────────────────

    def get_closed_trades(self) -> List[DecisionRecord]:
        """Get all trades with outcomes."""
        return [r for r in self.records if r.outcome is not None]

    def thesis_accuracy_by_regime(self) -> Dict[str, Dict[str, float]]:
        """Measure thesis accuracy per regime.

        Returns: {regime: {direction_acc, magnitude_acc, timing_acc, count}}
        """
        by_regime: Dict[str, List[DecisionRecord]] = {}
        for record in self.get_closed_trades():
            regime = record.regime
            if regime not in by_regime:
                by_regime[regime] = []
            by_regime[regime].append(record)

        results = {}
        for regime, records in by_regime.items():
            if not records:
                continue

            direction_hits = sum(1 for r in records if r.outcome.direction_correct)
            direction_acc = direction_hits / len(records)

            # Magnitude accuracy: how close was our target?
            magnitude_errors = []
            for r in records:
                if r.thesis.target and r.outcome:
                    actual_move_pct = (r.outcome.magnitude / 100.0)  # Convert from pct to decimal
                    predicted_move_pct = (r.thesis.target - r.execution_price) / r.execution_price if r.execution_price else 0
                    error = abs(actual_move_pct - predicted_move_pct)
                    magnitude_errors.append(error)

            magnitude_acc = 1.0 - (sum(magnitude_errors) / len(magnitude_errors)) if magnitude_errors else 0.5

            # Timing accuracy: did we get there in time?
            timing_acc = 0.5  # Placeholder

            results[regime] = {
                "direction_acc": direction_acc,
                "magnitude_acc": magnitude_acc,
                "timing_acc": timing_acc,
                "count": len(records),
            }

        return results

    def agent_accuracy_by_regime(self, agent: str) -> Dict[str, float]:
        """Get agent's win rate per regime."""
        by_regime: Dict[str, List[DecisionRecord]] = {}

        for record in self.get_closed_trades():
            if record.agent != agent:
                continue

            regime = record.regime
            if regime not in by_regime:
                by_regime[regime] = []
            by_regime[regime].append(record)

        results = {}
        for regime, records in by_regime.items():
            if not records:
                continue

            wins = sum(1 for r in records if r.outcome and r.outcome.pnl > 0)
            win_rate = wins / len(records)
            results[regime] = win_rate

        return results

    def setup_type_performance(self) -> Dict[str, Dict[str, float]]:
        """Performance by setup type.

        Returns: {setup_type: {wr, avg_pnl, count}}
        """
        by_setup: Dict[str, List[DecisionRecord]] = {}

        for record in self.get_closed_trades():
            setup = record.setup_type
            if setup not in by_setup:
                by_setup[setup] = []
            by_setup[setup].append(record)

        results = {}
        for setup, records in by_setup.items():
            if not records:
                continue

            wins = sum(1 for r in records if r.outcome and r.outcome.pnl > 0)
            wr = wins / len(records)

            avg_pnl = sum(r.outcome.pnl for r in records if r.outcome) / len(records)

            results[setup] = {
                "wr": wr,
                "avg_pnl": avg_pnl,
                "count": len(records),
            }

        return results

    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get summary stats for last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [r for r in self.records if r.timestamp_entry >= cutoff]
        closed = [r for r in recent if r.outcome]

        total_pnl = sum(r.outcome.pnl for r in closed if r.outcome)
        wins = sum(1 for r in closed if r.outcome and r.outcome.pnl > 0)
        wr = wins / len(closed) if closed else 0.5

        return {
            "total_decisions": len(recent),
            "executed": sum(1 for r in recent if r.executed),
            "closed_trades": len(closed),
            "total_pnl": total_pnl,
            "win_rate": wr,
            "avg_confidence": sum(r.confidence for r in recent) / len(recent) if recent else 0.5,
            "thesis_accuracy": self.thesis_accuracy_by_regime(),
            "setup_performance": self.setup_type_performance(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL LEDGER INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

_global_ledger: Optional[DecisionLedger] = None


def get_decision_ledger() -> DecisionLedger:
    """Get or create the global decision ledger."""
    global _global_ledger
    if _global_ledger is None:
        _global_ledger = DecisionLedger()
    return _global_ledger


__all__ = [
    "DecisionThesis",
    "DecisionOutcome",
    "DecisionRecord",
    "DecisionLedger",
    "get_decision_ledger",
]
