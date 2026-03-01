"""
Explainability & Transparency Layer — Why did parameters change?

Every time the system changes a parameter (confidence floor, leverage cap,
strategy weight, etc.), this module records:
1. WHAT changed (parameter name, old value, new value)
2. WHY it changed (the evidence/trigger)
3. WHO changed it (which system component)
4. WHEN it changed (timestamp)
5. IMPACT so far (performance since change)

This creates a complete audit trail that both the user and the LLM can review.

Usage:
    explainer = get_explainer()
    explainer.record_change(
        parameter="confidence_floor",
        old_value=65.0,
        new_value=72.0,
        reason="60-65% confidence bin has 30% WR over 10 trades",
        source="adaptive_confidence",
        context={"bin": "60-65", "wr": 0.30, "trades": 10},
    )
    report = explainer.get_recent_changes()
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.growth.explainability")

_DATA_DIR = os.path.join("data", "llm", "growth")
_CHANGES_FILE = "parameter_changes.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


@dataclass
class ParameterChange:
    """A single parameter change with full context."""
    change_id: str
    parameter: str              # "confidence_floor", "leverage_cap", "strategy_weight.regime_trend"
    old_value: Any
    new_value: Any
    reason: str                 # Human-readable explanation
    source: str                 # "adaptive_confidence", "parameter_tuner", "llm_decision", "backtest"
    timestamp: float = 0.0
    context: Dict[str, Any] = field(default_factory=dict)

    # Performance tracking (filled over time)
    trades_since_change: int = 0
    wins_since_change: int = 0
    pnl_since_change: float = 0.0
    impact_assessed: bool = False
    impact_was_positive: Optional[bool] = None
    impact_notes: str = ""

    @property
    def win_rate_since(self) -> float:
        if self.trades_since_change == 0:
            return 0.0
        return self.wins_since_change / self.trades_since_change

    @property
    def change_magnitude(self) -> float:
        """How big was the change (as fraction)."""
        try:
            old = float(self.old_value)
            new = float(self.new_value)
            if old == 0:
                return 0.0
            return abs(new - old) / abs(old)
        except (ValueError, TypeError):
            return 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ParameterChange":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ExplainabilityEngine:
    """Records and explains all parameter changes in the system."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._changes: List[ParameterChange] = []
        self._active_changes: Dict[str, ParameterChange] = {}  # param -> most recent change
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _CHANGES_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._changes = [ParameterChange.from_dict(c) for c in data.get("changes", [])]
                # Rebuild active changes (most recent per parameter)
                for c in self._changes:
                    if not c.impact_assessed:
                        self._active_changes[c.parameter] = c
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[EXPLAIN] Failed to load: {e}")

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _CHANGES_FILE)
        if len(self._changes) > 1000:
            self._changes = sorted(self._changes, key=lambda c: c.timestamp, reverse=True)[:1000]
        try:
            with open(path, "w") as f:
                json.dump({
                    "changes": [c.to_dict() for c in self._changes],
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[EXPLAIN] Failed to save: {e}")

    def record_change(
        self,
        parameter: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        source: str,
        context: Dict = None,
    ) -> ParameterChange:
        """Record a parameter change with explanation."""
        self._ensure_loaded()

        # Assess previous change for this parameter if exists
        if parameter in self._active_changes:
            prev = self._active_changes[parameter]
            if prev.trades_since_change >= 5:
                prev.impact_assessed = True
                prev.impact_was_positive = prev.pnl_since_change > 0
                prev.impact_notes = (
                    f"WR: {prev.win_rate_since:.0%} over {prev.trades_since_change} trades, "
                    f"PnL: ${prev.pnl_since_change:+.2f}"
                )

        change = ParameterChange(
            change_id=f"chg_{int(time.time())}_{parameter.replace('.', '_')}",
            parameter=parameter,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            source=source,
            timestamp=time.time(),
            context=context or {},
        )

        self._changes.append(change)
        self._active_changes[parameter] = change
        self._save()

        logger.info(
            f"[EXPLAIN] {parameter}: {old_value} -> {new_value} "
            f"| Reason: {reason[:80]} | Source: {source}"
        )
        return change

    def record_trade_outcome(self, win: bool, pnl: float):
        """Update all active (unassessed) changes with trade outcome."""
        self._ensure_loaded()
        for change in self._active_changes.values():
            if not change.impact_assessed:
                change.trades_since_change += 1
                if win:
                    change.wins_since_change += 1
                change.pnl_since_change += pnl

                # Auto-assess after enough trades
                if change.trades_since_change >= 20:
                    change.impact_assessed = True
                    change.impact_was_positive = change.pnl_since_change > 0
                    change.impact_notes = (
                        f"WR: {change.win_rate_since:.0%} over "
                        f"{change.trades_since_change} trades, "
                        f"PnL: ${change.pnl_since_change:+.2f}"
                    )
        self._save()

    def get_recent_changes(self, limit: int = 20, parameter: str = None) -> List[ParameterChange]:
        """Get recent parameter changes, optionally filtered."""
        self._ensure_loaded()
        changes = self._changes
        if parameter:
            changes = [c for c in changes if c.parameter == parameter]
        return sorted(changes, key=lambda c: c.timestamp, reverse=True)[:limit]

    def get_active_changes(self) -> Dict[str, ParameterChange]:
        """Get the currently active (most recent) change per parameter."""
        self._ensure_loaded()
        return dict(self._active_changes)

    def get_change_effectiveness(self) -> Dict[str, Dict[str, Any]]:
        """Get effectiveness summary by source."""
        self._ensure_loaded()
        by_source = defaultdict(lambda: {"total": 0, "positive": 0, "negative": 0, "pending": 0})
        for c in self._changes:
            bucket = by_source[c.source]
            bucket["total"] += 1
            if c.impact_assessed:
                if c.impact_was_positive:
                    bucket["positive"] += 1
                else:
                    bucket["negative"] += 1
            else:
                bucket["pending"] += 1
        return dict(by_source)

    def format_telegram(self, limit: int = 10) -> str:
        """Format recent changes for Telegram display."""
        self._ensure_loaded()
        recent = self.get_recent_changes(limit=limit)
        if not recent:
            return "No parameter changes recorded."

        lines = ["*Parameter Change Log*\n"]
        for c in recent:
            # Impact indicator
            if c.impact_assessed:
                impact = "+" if c.impact_was_positive else "-"
            elif c.trades_since_change > 0:
                impact = f"~{c.win_rate_since:.0%}"
            else:
                impact = "..."

            age_h = (time.time() - c.timestamp) / 3600
            age_str = f"{age_h:.0f}h ago" if age_h < 48 else f"{age_h/24:.0f}d ago"

            lines.append(
                f"[{impact}] `{c.parameter}`: {c.old_value} -> {c.new_value}\n"
                f"    Why: {c.reason[:80]}\n"
                f"    Source: {c.source} | {age_str}"
            )

        # Source effectiveness
        effectiveness = self.get_change_effectiveness()
        if effectiveness:
            lines.append("\n*Source Effectiveness:*")
            for src, data in effectiveness.items():
                if data["total"] >= 3:
                    assessed = data["positive"] + data["negative"]
                    if assessed > 0:
                        acc = data["positive"] / assessed
                        lines.append(f"  {src}: {acc:.0%} positive ({assessed} assessed)")

        return "\n".join(lines)

    def format_for_llm_prompt(self, limit: int = 5) -> str:
        """Format for LLM prompt injection — compact, actionable."""
        self._ensure_loaded()
        recent = self.get_recent_changes(limit=limit)
        if not recent:
            return ""

        lines = ["RECENT PARAMETER CHANGES:"]
        for c in recent:
            impact_str = ""
            if c.impact_assessed:
                impact_str = f" -> {'POSITIVE' if c.impact_was_positive else 'NEGATIVE'}"
            elif c.trades_since_change > 0:
                impact_str = f" -> tracking ({c.win_rate_since:.0%} WR, {c.trades_since_change} trades)"
            lines.append(
                f"  {c.parameter}: {c.old_value} -> {c.new_value} "
                f"({c.reason[:60]}){impact_str}"
            )

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────

_engine: Optional[ExplainabilityEngine] = None


def get_explainer() -> ExplainabilityEngine:
    """Get the singleton ExplainabilityEngine."""
    global _engine
    if _engine is None:
        _engine = ExplainabilityEngine()
    return _engine
