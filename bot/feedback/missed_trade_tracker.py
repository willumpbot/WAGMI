"""
Missed Trade Tracker: Comprehensive feedback loop for rejected/vetoed signals.

Captures EVERY signal that was considered but not executed, with:
1. Full signal context (symbol, side, confidence, strategies, regime)
2. Rejection reason and gate that blocked it
3. Counterfactual outcome (what WOULD have happened — did price move in predicted direction?)
4. Missed alpha calculation (profit left on the table)
5. Categorization by rejection type for systematic analysis

Works in BOTH backtest and live trading.

Output: missed_trades.jsonl (append-only) + summary report
"""

import json
import logging
import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.missed_trade_tracker")


@dataclass
class MissedTrade:
    """A single missed trade with full context and counterfactual."""
    # Signal context
    symbol: str
    side: str  # BUY or SELL
    confidence: float
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    atr: float

    # Rejection info
    rejection_gate: str  # Which gate blocked it
    rejection_reason: str  # Detailed reason
    rejection_category: str  # High-level category

    # Strategy context
    strategies_agreeing: List[str] = field(default_factory=list)
    num_agree: int = 0
    regime: str = "unknown"
    ev_per_dollar: float = 0.0

    # Counterfactual outcome (filled after price data available)
    price_after_1h: Optional[float] = None
    price_after_4h: Optional[float] = None
    price_after_8h: Optional[float] = None
    price_max_favorable: Optional[float] = None  # Best price in predicted direction
    price_max_adverse: Optional[float] = None  # Worst price against prediction
    would_have_hit_tp1: bool = False
    would_have_hit_sl: bool = False
    would_have_won: Optional[bool] = None  # True if TP1 hit before SL
    missed_pnl_estimate: float = 0.0  # Estimated PnL if trade was taken

    # Metadata
    timestamp: str = ""
    candle_idx: int = 0


# Rejection categories for systematic analysis
REJECTION_CATEGORIES = {
    # Ensemble-level rejections
    "insufficient_votes": "ensemble",
    "negative_ev": "ensemble",
    "opposition_veto": "ensemble",
    "confidence_floor": "ensemble",
    "chop_filter": "ensemble",
    "losing_combo": "ensemble",
    "regime_blocked": "ensemble",

    # Risk pipeline rejections
    "invalid_signal": "signal_quality",
    "rr_too_low": "signal_quality",
    "fee_drag": "signal_quality",
    "ev_floor": "signal_quality",
    "circuit_breaker": "risk_management",
    "max_positions": "capacity",
    "correlation_cluster": "portfolio",
    "leverage_denied": "risk_management",
    "leverage_gate": "risk_management",
    "lev_ev_floor": "risk_management",
    "liquidation_risk": "risk_management",
    "position_size_zero": "risk_management",

    # LLM-level rejections
    "llm_veto": "llm",
    "llm_skip": "llm",

    # Other
    "cooldown": "timing",
    "dedup": "timing",
}


def classify_rejection(reason: str) -> str:
    """Classify a rejection reason string into a high-level category."""
    reason_lower = reason.lower()
    if "circuit breaker" in reason_lower:
        return "circuit_breaker"
    if "max position" in reason_lower:
        return "max_positions"
    if "correlation" in reason_lower or "cluster" in reason_lower:
        return "correlation_cluster"
    if "fee drag" in reason_lower:
        return "fee_drag"
    if "ev " in reason_lower and "low" in reason_lower:
        return "ev_floor"
    if "ev " in reason_lower and "lever" in reason_lower:
        return "lev_ev_floor"
    if "r:r" in reason_lower or "rr " in reason_lower:
        return "rr_too_low"
    if "leverage denied" in reason_lower:
        return "leverage_denied"
    if "leverage gate" in reason_lower or "below leverage" in reason_lower:
        return "leverage_gate"
    if "liquidation" in reason_lower:
        return "liquidation_risk"
    if "position size zero" in reason_lower or "stop width" in reason_lower:
        return "position_size_zero"
    if "invalid" in reason_lower:
        return "invalid_signal"
    if "negative ev" in reason_lower:
        return "negative_ev"
    if "veto" in reason_lower:
        return "opposition_veto"
    if "chop" in reason_lower:
        return "chop_filter"
    if "confidence" in reason_lower and "floor" in reason_lower:
        return "confidence_floor"
    if "votes" in reason_lower or "agree" in reason_lower:
        return "insufficient_votes"
    if "combo" in reason_lower or "losing" in reason_lower:
        return "losing_combo"
    if "regime" in reason_lower:
        return "regime_blocked"
    if "cooldown" in reason_lower:
        return "cooldown"
    if "dedup" in reason_lower:
        return "dedup"
    if "llm" in reason_lower and "veto" in reason_lower:
        return "llm_veto"
    if "llm" in reason_lower:
        return "llm_skip"
    return "unknown"


class MissedTradeTracker:
    """
    Tracks all missed trades with counterfactual analysis.

    Usage:
        tracker = MissedTradeTracker(data_dir="data")

        # Record a missed trade when a signal is rejected
        tracker.record_rejection(signal, reason="Fee drag 42% > 30%", gate="fee_drag")

        # After price data is available, compute counterfactuals
        tracker.compute_counterfactuals(price_series)

        # Generate report
        report = tracker.generate_report()
    """

    def __init__(self, data_dir: str = "data"):
        self._data_dir = data_dir
        self._output_file = os.path.join(data_dir, "missed_trades.jsonl")
        self._lock = threading.Lock()
        self._pending_counterfactuals: List[MissedTrade] = []
        self._session_misses: List[MissedTrade] = []

    def record_rejection(
        self,
        signal,
        reason: str,
        gate: str = "unknown",
        candle_idx: int = 0,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a rejected signal with full context.

        Args:
            signal: The Signal object that was rejected
            reason: Detailed rejection reason string
            gate: Which gate/stage rejected it
            candle_idx: Current candle index (for backtest counterfactual matching)
            timestamp: ISO timestamp string
        """
        category = classify_rejection(reason)
        meta = signal.metadata or {}

        missed = MissedTrade(
            symbol=signal.symbol,
            side=signal.side,
            confidence=signal.confidence,
            entry_price=signal.entry,
            sl_price=signal.sl,
            tp1_price=signal.tp1,
            tp2_price=signal.tp2 if hasattr(signal, 'tp2') else signal.tp1,
            atr=signal.atr if hasattr(signal, 'atr') else 0.0,
            rejection_gate=gate,
            rejection_reason=reason,
            rejection_category=category,
            strategies_agreeing=meta.get("strategies_agree", []),
            num_agree=meta.get("num_agree", 1),
            regime=meta.get("regime", meta.get("bt_regime_raw", "unknown")),
            ev_per_dollar=meta.get("ev_per_dollar", 0.0),
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            candle_idx=candle_idx,
        )

        with self._lock:
            self._session_misses.append(missed)
            self._pending_counterfactuals.append(missed)

        logger.debug(
            f"[MISSED] {signal.symbol} {signal.side} conf={signal.confidence:.0f}% "
            f"rejected at {gate}: {reason} (category={category})"
        )

    def record_ensemble_rejection(
        self,
        symbol: str,
        signals: List,
        reason: str,
        candle_idx: int = 0,
        timestamp: Optional[str] = None,
        regime: str = "unknown",
    ) -> None:
        """Record when ensemble voting rejects a set of signals.

        Used for cases where individual strategies fired but ensemble
        didn't produce a merged signal (insufficient votes, veto, etc.)
        """
        if not signals:
            return

        # Take the strongest signal as representative
        best = max(signals, key=lambda s: s.confidence)
        category = classify_rejection(reason)

        missed = MissedTrade(
            symbol=symbol,
            side=best.side,
            confidence=best.confidence,
            entry_price=best.entry,
            sl_price=best.sl,
            tp1_price=best.tp1,
            tp2_price=best.tp2 if hasattr(best, 'tp2') else best.tp1,
            atr=best.atr if hasattr(best, 'atr') else 0.0,
            rejection_gate="ensemble",
            rejection_reason=reason,
            rejection_category=category,
            strategies_agreeing=[s.strategy for s in signals],
            num_agree=len(signals),
            regime=regime,
            ev_per_dollar=0.0,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            candle_idx=candle_idx,
        )

        with self._lock:
            self._session_misses.append(missed)
            self._pending_counterfactuals.append(missed)

    def compute_counterfactuals(
        self,
        symbol: str,
        price_series: List[float],
        start_idx: int = 0,
        candle_duration_hours: float = 1.0,
    ) -> None:
        """Compute what WOULD have happened for pending missed trades.

        Args:
            symbol: Symbol to compute counterfactuals for
            price_series: Full price series (close prices, 1h candles)
            start_idx: Starting candle index of the price series
            candle_duration_hours: Duration of each candle
        """
        with self._lock:
            pending = [m for m in self._pending_counterfactuals if m.symbol == symbol]

        for missed in pending:
            idx = missed.candle_idx - start_idx
            if idx < 0 or idx >= len(price_series):
                continue

            is_long = missed.side == "BUY"

            # Look ahead 1h, 4h, 8h
            lookahead_candles = {
                "1h": 1,
                "4h": int(4 / candle_duration_hours),
                "8h": int(8 / candle_duration_hours),
            }

            for label, n_candles in lookahead_candles.items():
                future_idx = idx + n_candles
                if future_idx < len(price_series):
                    price = price_series[future_idx]
                    if label == "1h":
                        missed.price_after_1h = price
                    elif label == "4h":
                        missed.price_after_4h = price
                    elif label == "8h":
                        missed.price_after_8h = price

            # Check max favorable/adverse excursion over 8h window
            end_idx = min(idx + int(8 / candle_duration_hours), len(price_series))
            future_prices = price_series[idx:end_idx]

            if future_prices:
                if is_long:
                    missed.price_max_favorable = max(future_prices)
                    missed.price_max_adverse = min(future_prices)
                else:
                    missed.price_max_favorable = min(future_prices)
                    missed.price_max_adverse = max(future_prices)

                # Would TP1 or SL have been hit?
                for p in future_prices:
                    if is_long:
                        if p >= missed.tp1_price:
                            missed.would_have_hit_tp1 = True
                        if p <= missed.sl_price:
                            missed.would_have_hit_sl = True
                    else:
                        if p <= missed.tp1_price:
                            missed.would_have_hit_tp1 = True
                        if p >= missed.sl_price:
                            missed.would_have_hit_sl = True

                # Determine if trade would have won (TP1 hit before SL)
                tp1_first = False
                sl_first = False
                for p in future_prices:
                    if is_long:
                        if p >= missed.tp1_price and not sl_first:
                            tp1_first = True
                            break
                        if p <= missed.sl_price:
                            sl_first = True
                            break
                    else:
                        if p <= missed.tp1_price and not sl_first:
                            tp1_first = True
                            break
                        if p >= missed.sl_price:
                            sl_first = True
                            break

                if tp1_first:
                    missed.would_have_won = True
                    # Estimate PnL: (TP1 - entry) / entry * 100 as pct
                    if is_long:
                        missed.missed_pnl_estimate = (missed.tp1_price - missed.entry_price) / missed.entry_price * 100
                    else:
                        missed.missed_pnl_estimate = (missed.entry_price - missed.tp1_price) / missed.entry_price * 100
                elif sl_first:
                    missed.would_have_won = False
                    if is_long:
                        missed.missed_pnl_estimate = (missed.sl_price - missed.entry_price) / missed.entry_price * 100
                    else:
                        missed.missed_pnl_estimate = (missed.entry_price - missed.sl_price) / missed.entry_price * 100

        # Remove computed ones from pending
        with self._lock:
            self._pending_counterfactuals = [
                m for m in self._pending_counterfactuals if m.symbol != symbol
            ]

    def flush_to_disk(self) -> None:
        """Write all session misses to JSONL file (append-only)."""
        with self._lock:
            to_write = list(self._session_misses)

        if not to_write:
            return

        try:
            os.makedirs(os.path.dirname(self._output_file), exist_ok=True)
            with open(self._output_file, "a") as f:
                for missed in to_write:
                    line = json.dumps(asdict(missed), default=str)
                    f.write(line + "\n")
            logger.info(f"[MISSED] Flushed {len(to_write)} missed trades to {self._output_file}")
        except Exception as e:
            logger.warning(f"[MISSED] Failed to flush: {e}")

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive missed trade report.

        Returns summary with:
        - Total missed trades by category
        - Would-have-won rate per category
        - Missed alpha (total PnL left on table)
        - Top missed opportunities
        - Gate effectiveness (% of rejections that were correct)
        """
        with self._lock:
            misses = list(self._session_misses)

        if not misses:
            return {"total_missed": 0, "message": "No missed trades recorded"}

        # Count by category
        by_category = defaultdict(list)
        for m in misses:
            cat = REJECTION_CATEGORIES.get(m.rejection_category, "unknown")
            by_category[m.rejection_category].append(m)

        # Category summary
        category_summary = {}
        for cat, trades in by_category.items():
            with_outcome = [t for t in trades if t.would_have_won is not None]
            would_have_won = [t for t in with_outcome if t.would_have_won]
            would_have_lost = [t for t in with_outcome if not t.would_have_won]
            missed_alpha = sum(t.missed_pnl_estimate for t in trades if t.would_have_won)
            saved_loss = sum(abs(t.missed_pnl_estimate) for t in trades if t.would_have_won is False)

            category_summary[cat] = {
                "count": len(trades),
                "with_outcome": len(with_outcome),
                "would_have_won": len(would_have_won),
                "would_have_lost": len(would_have_lost),
                "win_rate_if_taken": round(len(would_have_won) / max(len(with_outcome), 1) * 100, 1),
                "missed_alpha_pct": round(missed_alpha, 3),
                "saved_loss_pct": round(saved_loss, 3),
                "net_impact_pct": round(missed_alpha - saved_loss, 3),
                "gate_accuracy_pct": round(
                    len(would_have_lost) / max(len(with_outcome), 1) * 100, 1
                ),  # % of rejections that were correct (would have lost)
            }

        # Top missed opportunities (biggest potential winners that were blocked)
        winners_missed = sorted(
            [m for m in misses if m.would_have_won],
            key=lambda m: m.missed_pnl_estimate,
            reverse=True,
        )[:10]

        top_missed = [
            {
                "symbol": m.symbol,
                "side": m.side,
                "confidence": m.confidence,
                "entry": m.entry_price,
                "missed_pnl_pct": round(m.missed_pnl_estimate, 3),
                "rejected_by": m.rejection_gate,
                "reason": m.rejection_reason,
                "regime": m.regime,
                "strategies": m.strategies_agreeing,
            }
            for m in winners_missed
        ]

        # By symbol
        by_symbol = defaultdict(int)
        for m in misses:
            by_symbol[m.symbol] += 1

        # By regime
        by_regime = defaultdict(int)
        for m in misses:
            by_regime[m.regime] += 1

        # Overall stats
        with_outcome = [m for m in misses if m.would_have_won is not None]
        total_missed_alpha = sum(m.missed_pnl_estimate for m in misses if m.would_have_won)
        total_saved = sum(abs(m.missed_pnl_estimate) for m in misses if m.would_have_won is False)

        return {
            "total_missed": len(misses),
            "with_counterfactual": len(with_outcome),
            "would_have_won": sum(1 for m in with_outcome if m.would_have_won),
            "would_have_lost": sum(1 for m in with_outcome if not m.would_have_won),
            "overall_gate_accuracy_pct": round(
                sum(1 for m in with_outcome if not m.would_have_won)
                / max(len(with_outcome), 1) * 100, 1
            ),
            "total_missed_alpha_pct": round(total_missed_alpha, 3),
            "total_saved_loss_pct": round(total_saved, 3),
            "net_gate_value_pct": round(total_saved - total_missed_alpha, 3),
            "by_category": category_summary,
            "by_symbol": dict(by_symbol),
            "by_regime": dict(by_regime),
            "top_missed_opportunities": top_missed,
        }

    def get_gate_effectiveness(self) -> Dict[str, Dict[str, float]]:
        """Get per-gate effectiveness: what % of rejections were correct?

        A gate is effective if most trades it rejects would have lost.
        A gate is harmful if it blocks too many would-be winners.
        """
        with self._lock:
            misses = list(self._session_misses)

        by_gate = defaultdict(list)
        for m in misses:
            if m.would_have_won is not None:
                by_gate[m.rejection_gate].append(m)

        result = {}
        for gate, trades in by_gate.items():
            won = sum(1 for t in trades if t.would_have_won)
            lost = sum(1 for t in trades if not t.would_have_won)
            total = len(trades)
            result[gate] = {
                "total_rejections": total,
                "correct_rejections": lost,  # Would have lost — gate saved us
                "incorrect_rejections": won,  # Would have won — gate cost us
                "accuracy_pct": round(lost / max(total, 1) * 100, 1),
                "recommendation": (
                    "KEEP" if lost / max(total, 1) >= 0.55
                    else "REVIEW" if lost / max(total, 1) >= 0.45
                    else "LOOSEN — blocking too many winners"
                ),
            }

        return result

    def clear_session(self) -> None:
        """Clear session data (call between backtests or trading sessions)."""
        with self._lock:
            self._session_misses.clear()
            self._pending_counterfactuals.clear()
