"""
Veto Feedback Loop — Track veto accuracy and feed results back to LLM.

When the LLM vetoes a trade (action=flat), the trade never executes.
But we STILL need to know: "Would that trade have won or lost?"

This module:
1. Records every veto with the signal that was vetoed
2. Tracks what would have happened (using subsequent price data)
3. Scores veto accuracy (correct veto = would have lost, incorrect = would have won)
4. Feeds veto performance back into LLM memory
5. Identifies veto patterns (what types of vetoes are most accurate)
6. Generates recommendations based on veto analysis

Usage:
    tracker = get_veto_tracker()
    tracker.record_veto(symbol="BTC", side="LONG", confidence=72,
                        entry=65000, sl=64000, tp1=67000,
                        llm_reason="High funding, likely reversal",
                        regime="trending", trigger="PRE_TRADE")
    # Later, when we have price data:
    tracker.resolve_veto(symbol="BTC", veto_ts=..., outcome_price=63500)
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.llm.growth.veto_feedback")

_DATA_DIR = os.path.join("data", "llm", "growth")
_VETO_FILE = "veto_tracker.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


@dataclass
class VetoRecord:
    """A single veto event with hypothetical outcome tracking."""
    veto_id: str
    symbol: str
    side: str
    confidence: float
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float = 0.0
    llm_reason: str = ""
    regime: str = ""
    trigger: str = ""
    strategies_agreed: int = 0
    veto_ts: float = 0.0

    # Outcome tracking (filled later)
    resolved: bool = False
    resolved_ts: float = 0.0
    hypothetical_outcome: str = ""        # "would_have_won", "would_have_lost", "unclear"
    max_favorable_move: float = 0.0       # Best price move in trade direction
    max_adverse_move: float = 0.0         # Worst price move against trade
    would_have_hit_sl: bool = False
    would_have_hit_tp1: bool = False
    would_have_hit_tp2: bool = False
    veto_was_correct: Optional[bool] = None
    estimated_pnl_saved: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VetoRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class VetoTracker:
    """Tracks veto accuracy and provides feedback for LLM learning."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._vetoes: List[VetoRecord] = []
        self._stats: Dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _VETO_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._vetoes = [VetoRecord.from_dict(v) for v in data.get("vetoes", [])]
                self._stats = data.get("stats", {})
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[VETO] Failed to load: {e}")

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _VETO_FILE)
        # Keep last 500 vetoes
        if len(self._vetoes) > 500:
            self._vetoes = sorted(self._vetoes, key=lambda v: v.veto_ts, reverse=True)[:500]
        try:
            with open(path, "w") as f:
                json.dump({
                    "vetoes": [v.to_dict() for v in self._vetoes],
                    "stats": self._stats,
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[VETO] Failed to save: {e}")

    def record_veto(
        self,
        symbol: str,
        side: str,
        confidence: float,
        entry_price: float,
        sl_price: float,
        tp1_price: float,
        tp2_price: float = 0.0,
        llm_reason: str = "",
        regime: str = "",
        trigger: str = "",
        strategies_agreed: int = 0,
    ) -> str:
        """Record a new veto event. Returns the veto_id."""
        self._ensure_loaded()

        veto_id = f"veto_{int(time.time())}_{symbol}"
        veto = VetoRecord(
            veto_id=veto_id,
            symbol=symbol,
            side=side.upper(),
            confidence=confidence,
            entry_price=entry_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            llm_reason=llm_reason,
            regime=regime,
            trigger=trigger,
            strategies_agreed=strategies_agreed,
            veto_ts=time.time(),
        )

        self._vetoes.append(veto)
        self._save()

        logger.info(
            f"[VETO] Recorded: {symbol} {side} at {entry_price} "
            f"(conf={confidence:.0f}%, regime={regime}) — {llm_reason[:60]}"
        )
        return veto_id

    def resolve_veto(
        self,
        veto_id: str = None,
        symbol: str = None,
        veto_ts: float = None,
        price_high: float = 0.0,
        price_low: float = 0.0,
        price_close: float = 0.0,
        resolution_window_s: float = 3600,
    ) -> Optional[VetoRecord]:
        """Resolve a veto by checking what would have happened.

        Uses the high/low/close prices over the resolution window to determine
        if the vetoed trade would have hit SL, TP1, or TP2.
        """
        self._ensure_loaded()

        # Find the veto
        veto = None
        if veto_id:
            veto = next((v for v in self._vetoes if v.veto_id == veto_id), None)
        elif symbol and veto_ts:
            # Find closest unresolved veto for this symbol
            candidates = [
                v for v in self._vetoes
                if v.symbol == symbol and not v.resolved
                and abs(v.veto_ts - veto_ts) < 300
            ]
            if candidates:
                veto = min(candidates, key=lambda v: abs(v.veto_ts - veto_ts))

        if not veto:
            return None

        # Determine hypothetical outcome
        is_long = veto.side in ("LONG", "BUY")

        if is_long:
            veto.max_favorable_move = price_high - veto.entry_price
            veto.max_adverse_move = veto.entry_price - price_low
            veto.would_have_hit_sl = price_low <= veto.sl_price
            veto.would_have_hit_tp1 = price_high >= veto.tp1_price
            veto.would_have_hit_tp2 = veto.tp2_price > 0 and price_high >= veto.tp2_price
        else:
            veto.max_favorable_move = veto.entry_price - price_low
            veto.max_adverse_move = price_high - veto.entry_price
            veto.would_have_hit_sl = price_high >= veto.sl_price
            veto.would_have_hit_tp1 = price_low <= veto.tp1_price
            veto.would_have_hit_tp2 = veto.tp2_price > 0 and price_low <= veto.tp2_price

        # Determine overall outcome
        if veto.would_have_hit_sl and not veto.would_have_hit_tp1:
            veto.hypothetical_outcome = "would_have_lost"
            veto.veto_was_correct = True
            # Estimate saved PnL (rough: SL distance * assumed size)
            sl_dist = abs(veto.entry_price - veto.sl_price) / veto.entry_price
            veto.estimated_pnl_saved = sl_dist * 100  # as percentage
        elif veto.would_have_hit_tp1:
            veto.hypothetical_outcome = "would_have_won"
            veto.veto_was_correct = False
            tp_dist = abs(veto.tp1_price - veto.entry_price) / veto.entry_price
            veto.estimated_pnl_saved = -(tp_dist * 100)  # negative = missed opportunity
        else:
            # Neither SL nor TP1 hit — check close vs entry
            if is_long:
                pnl_pct = (price_close - veto.entry_price) / veto.entry_price * 100
            else:
                pnl_pct = (veto.entry_price - price_close) / veto.entry_price * 100

            if pnl_pct < -1.0:
                veto.hypothetical_outcome = "would_have_lost"
                veto.veto_was_correct = True
                veto.estimated_pnl_saved = abs(pnl_pct)
            elif pnl_pct > 1.0:
                veto.hypothetical_outcome = "would_have_won"
                veto.veto_was_correct = False
                veto.estimated_pnl_saved = -pnl_pct
            else:
                veto.hypothetical_outcome = "unclear"
                veto.veto_was_correct = None
                veto.estimated_pnl_saved = 0.0

        veto.resolved = True
        veto.resolved_ts = time.time()

        self._update_stats()
        self._save()

        outcome_str = (
            "CORRECT (would have lost)"
            if veto.veto_was_correct is True
            else "INCORRECT (would have won)"
            if veto.veto_was_correct is False
            else "UNCLEAR"
        )
        logger.info(
            f"[VETO] Resolved: {veto.symbol} {veto.side} — {outcome_str} "
            f"(saved ~{veto.estimated_pnl_saved:+.1f}%)"
        )
        return veto

    def check_unresolved(self, current_prices: Dict[str, Dict[str, float]]):
        """Check all unresolved vetoes against current price data.

        current_prices format: {"BTC": {"high": X, "low": Y, "close": Z}}
        """
        self._ensure_loaded()
        now = time.time()
        resolved_count = 0

        for veto in self._vetoes:
            if veto.resolved:
                continue
            # Only resolve if enough time has passed (1h default)
            if now - veto.veto_ts < 3600:
                continue

            prices = current_prices.get(veto.symbol)
            if not prices:
                continue

            self.resolve_veto(
                veto_id=veto.veto_id,
                price_high=prices.get("high", 0),
                price_low=prices.get("low", 0),
                price_close=prices.get("close", 0),
            )
            resolved_count += 1

        if resolved_count:
            logger.info(f"[VETO] Batch resolved {resolved_count} vetoes")

    def _update_stats(self):
        """Recalculate aggregate veto statistics."""
        resolved = [v for v in self._vetoes if v.resolved]
        if not resolved:
            return

        total = len(resolved)
        correct = sum(1 for v in resolved if v.veto_was_correct is True)
        incorrect = sum(1 for v in resolved if v.veto_was_correct is False)
        unclear = sum(1 for v in resolved if v.veto_was_correct is None)

        # By type analysis
        by_regime = defaultdict(lambda: {"total": 0, "correct": 0})
        by_trigger = defaultdict(lambda: {"total": 0, "correct": 0})
        by_symbol = defaultdict(lambda: {"total": 0, "correct": 0})
        by_side = defaultdict(lambda: {"total": 0, "correct": 0})

        for v in resolved:
            for bucket, key in [
                (by_regime, v.regime),
                (by_trigger, v.trigger),
                (by_symbol, v.symbol),
                (by_side, v.side),
            ]:
                if key:
                    bucket[key]["total"] += 1
                    if v.veto_was_correct is True:
                        bucket[key]["correct"] += 1

        self._stats = {
            "total_vetoes": len(self._vetoes),
            "resolved": total,
            "unresolved": len(self._vetoes) - total,
            "correct": correct,
            "incorrect": incorrect,
            "unclear": unclear,
            "accuracy": correct / (correct + incorrect) if (correct + incorrect) > 0 else 0,
            "total_pnl_saved": sum(v.estimated_pnl_saved for v in resolved if v.veto_was_correct),
            "total_missed_opportunity": abs(sum(
                v.estimated_pnl_saved for v in resolved
                if v.veto_was_correct is False
            )),
            "by_regime": {k: dict(v) for k, v in by_regime.items()},
            "by_trigger": {k: dict(v) for k, v in by_trigger.items()},
            "by_symbol": {k: dict(v) for k, v in by_symbol.items()},
            "by_side": {k: dict(v) for k, v in by_side.items()},
        }

    def get_accuracy(self) -> float:
        """Get overall veto accuracy."""
        self._ensure_loaded()
        self._update_stats()
        return self._stats.get("accuracy", 0.0)

    def get_stats(self) -> Dict[str, Any]:
        """Get full veto statistics."""
        self._ensure_loaded()
        self._update_stats()
        return self._stats

    def get_memory_feedback(self) -> Optional[str]:
        """Generate a memory update string for the LLM based on veto performance.

        This is injected into the LLM's memory to help it learn from its vetoes.
        """
        self._ensure_loaded()
        self._update_stats()

        stats = self._stats
        if stats.get("resolved", 0) < 5:
            return None

        parts = []

        accuracy = stats.get("accuracy", 0)
        parts.append(f"Veto accuracy: {accuracy:.0%} ({stats['correct']}/{stats['correct'] + stats['incorrect']})")

        if stats.get("total_pnl_saved", 0) > 0:
            parts.append(f"Total saved by correct vetoes: ~{stats['total_pnl_saved']:.1f}%")

        if stats.get("total_missed_opportunity", 0) > 0:
            parts.append(f"Missed opportunity from wrong vetoes: ~{stats['total_missed_opportunity']:.1f}%")

        # Best/worst categories
        for dimension, label in [("by_regime", "regime"), ("by_symbol", "symbol")]:
            dim_data = stats.get(dimension, {})
            best = None
            worst = None
            for key, data in dim_data.items():
                if data["total"] >= 3:
                    acc = data["correct"] / data["total"]
                    if best is None or acc > best[1]:
                        best = (key, acc)
                    if worst is None or acc < worst[1]:
                        worst = (key, acc)
            if best and best[1] > 0.6:
                parts.append(f"Best veto {label}: {best[0]} ({best[1]:.0%} accurate)")
            if worst and worst[1] < 0.4:
                parts.append(f"Worst veto {label}: {worst[0]} ({worst[1]:.0%} accurate — reconsider vetoing here)")

        return " | ".join(parts) if parts else None

    def format_telegram(self) -> str:
        """Format veto stats for Telegram display."""
        self._ensure_loaded()
        self._update_stats()
        stats = self._stats

        if not stats.get("resolved"):
            return "No vetoes resolved yet."

        lines = [
            "*Veto Feedback*\n",
            f"Total vetoes: {stats.get('total_vetoes', 0)} "
            f"(resolved: {stats.get('resolved', 0)})",
            f"Accuracy: {stats.get('accuracy', 0):.0%} "
            f"({stats.get('correct', 0)} correct, "
            f"{stats.get('incorrect', 0)} incorrect, "
            f"{stats.get('unclear', 0)} unclear)",
            f"PnL saved by vetoes: ~{stats.get('total_pnl_saved', 0):.1f}%",
            f"Missed opportunities: ~{stats.get('total_missed_opportunity', 0):.1f}%",
        ]

        # Recent vetoes
        recent = sorted(
            [v for v in self._vetoes if v.resolved],
            key=lambda v: v.resolved_ts, reverse=True
        )[:5]
        if recent:
            lines.append("\n*Recent Vetoes:*")
            for v in recent:
                icon = "Y" if v.veto_was_correct else ("N" if v.veto_was_correct is False else "?")
                lines.append(
                    f"  [{icon}] {v.symbol} {v.side} — {v.hypothetical_outcome} "
                    f"({v.estimated_pnl_saved:+.1f}%)"
                )

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────

_tracker: Optional[VetoTracker] = None


def get_veto_tracker() -> VetoTracker:
    """Get the singleton VetoTracker."""
    global _tracker
    if _tracker is None:
        _tracker = VetoTracker()
    return _tracker
