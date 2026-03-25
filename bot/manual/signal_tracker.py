"""
Signal Value Tracker — Quantifies every sniper signal's real-world outcome.

Every signal that passes the filter gets tracked:
1. Entry price at signal time
2. Price at +5min, +15min, +30min, +1h, +2h, +3h, +6h, +12h
3. Max favorable excursion (MFE) and max adverse excursion (MAE)
4. Whether TP/SL would have been hit and when
5. Actual PnL if traded at the signal's sizing

This gives us ground truth on the VALUE of each signal, independent of
whether the simulator or bot actually traded it.

Usage:
    tracker = SignalValueTracker()

    # On every sniper signal that passes filter:
    tracker.record_signal(sniper_signal)

    # On every price update (called from main loop):
    tracker.update_prices({"HYPE": 40.5, "BTC": 71000, "SOL": 135})

    # Get report:
    report = tracker.get_report()
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any

logger = logging.getLogger("bot.manual.signal_tracker")

_DATA_DIR = os.path.join("data", "manual")
_TRACKER_PATH = os.path.join(_DATA_DIR, "signal_value_tracker.jsonl")
_SUMMARY_PATH = os.path.join(_DATA_DIR, "signal_value_summary.json")

# Checkpoints: measure price at these intervals after signal
_CHECKPOINTS_S = [
    (5 * 60, "5min"),
    (15 * 60, "15min"),
    (30 * 60, "30min"),
    (60 * 60, "1h"),
    (2 * 3600, "2h"),
    (3 * 3600, "3h"),
    (6 * 3600, "6h"),
    (12 * 3600, "12h"),
]


@dataclass
class TrackedSignal:
    """A signal being tracked for value measurement."""
    signal_id: str
    symbol: str
    side: str            # "BUY" or "SELL"
    tier: str
    entry: float
    sl: float
    tp_scalp: float
    tp_swing: float
    leverage: float
    risk_pct: float
    risk_amount: float
    position_size_usd: float
    confidence: float
    num_agree: int
    regime: str
    is_dip_buy: bool
    quality_grade: str
    timestamp: float     # epoch when signal was generated

    # Tracking state
    checkpoints: Dict[str, Optional[float]] = field(default_factory=dict)
    mfe: float = 0.0            # Max favorable excursion (%)
    mae: float = 0.0            # Max adverse excursion (%)
    mfe_price: float = 0.0
    mae_price: float = 0.0
    tp_scalp_hit: bool = False
    tp_scalp_hit_at: Optional[float] = None   # seconds after signal
    tp_swing_hit: bool = False
    tp_swing_hit_at: Optional[float] = None
    sl_hit: bool = False
    sl_hit_at: Optional[float] = None
    resolved: bool = False       # True when all checkpoints filled or SL/TP hit
    last_price: float = 0.0
    last_update: float = 0.0


class SignalValueTracker:
    """Tracks every sniper signal's real-world price outcome."""

    def __init__(self, max_active: int = 100):
        os.makedirs(_DATA_DIR, exist_ok=True)
        self._active: Dict[str, TrackedSignal] = {}
        self._max_active = max_active
        self._signal_counter = 0
        self._total_tracked = 0
        self._total_tp_scalp_hits = 0
        self._total_sl_hits = 0
        self._total_time_expired = 0

        # Per-setup aggregates
        self._setup_results: Dict[str, Dict[str, Any]] = {}

    def record_signal(self, sniper_signal) -> str:
        """Start tracking a new signal. Returns signal_id."""
        self._signal_counter += 1
        signal_id = f"SV-{self._signal_counter:05d}"

        tracked = TrackedSignal(
            signal_id=signal_id,
            symbol=sniper_signal.symbol,
            side=sniper_signal.side,
            tier=sniper_signal.tier,
            entry=sniper_signal.entry,
            sl=sniper_signal.sl,
            tp_scalp=sniper_signal.tp_scalp,
            tp_swing=sniper_signal.tp_swing,
            leverage=sniper_signal.leverage,
            risk_pct=sniper_signal.risk_pct,
            risk_amount=sniper_signal.risk_amount,
            position_size_usd=sniper_signal.position_size_usd,
            confidence=sniper_signal.confidence,
            num_agree=sniper_signal.num_agree,
            regime=sniper_signal.regime,
            is_dip_buy=getattr(sniper_signal, 'is_dip_buy', False),
            quality_grade=getattr(sniper_signal, 'quality_grade', 'unknown'),
            timestamp=time.time(),
            mfe_price=sniper_signal.entry,
            mae_price=sniper_signal.entry,
            last_price=sniper_signal.entry,
            last_update=time.time(),
        )

        # Initialize checkpoint slots
        for _, label in _CHECKPOINTS_S:
            tracked.checkpoints[label] = None

        self._active[signal_id] = tracked
        self._total_tracked += 1

        # Evict oldest if over limit
        if len(self._active) > self._max_active:
            oldest_id = min(self._active, key=lambda k: self._active[k].timestamp)
            self._finalize_signal(oldest_id, "evicted")

        logger.debug(
            f"[TRACKER] Recording {signal_id}: {sniper_signal.symbol} "
            f"{sniper_signal.side} @ ${sniper_signal.entry:.2f} "
            f"tier={sniper_signal.tier} conf={sniper_signal.confidence:.0f}%"
        )
        return signal_id

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update all active signals with current prices. Call every scan cycle."""
        now = time.time()
        to_finalize = []

        for sig_id, sig in self._active.items():
            price = prices.get(sig.symbol)
            if price is None:
                continue

            sig.last_price = price
            sig.last_update = now
            elapsed = now - sig.timestamp

            # Update MFE/MAE
            if sig.side == "BUY":
                move_pct = (price - sig.entry) / sig.entry * 100
            else:
                move_pct = (sig.entry - price) / sig.entry * 100

            if move_pct > sig.mfe:
                sig.mfe = move_pct
                sig.mfe_price = price
            if move_pct < sig.mae:
                sig.mae = move_pct
                sig.mae_price = price

            # Check TP/SL hits
            if not sig.tp_scalp_hit:
                if sig.side == "BUY" and price >= sig.tp_scalp:
                    sig.tp_scalp_hit = True
                    sig.tp_scalp_hit_at = elapsed
                elif sig.side == "SELL" and price <= sig.tp_scalp:
                    sig.tp_scalp_hit = True
                    sig.tp_scalp_hit_at = elapsed

            if not sig.tp_swing_hit:
                if sig.side == "BUY" and price >= sig.tp_swing:
                    sig.tp_swing_hit = True
                    sig.tp_swing_hit_at = elapsed
                elif sig.side == "SELL" and price <= sig.tp_swing:
                    sig.tp_swing_hit = True
                    sig.tp_swing_hit_at = elapsed

            if not sig.sl_hit:
                if sig.side == "BUY" and price <= sig.sl:
                    sig.sl_hit = True
                    sig.sl_hit_at = elapsed
                elif sig.side == "SELL" and price >= sig.sl:
                    sig.sl_hit = True
                    sig.sl_hit_at = elapsed

            # Fill checkpoints
            for seconds, label in _CHECKPOINTS_S:
                if sig.checkpoints.get(label) is None and elapsed >= seconds:
                    sig.checkpoints[label] = price

            # Check if fully resolved (all checkpoints filled or SL hit)
            all_filled = all(v is not None for v in sig.checkpoints.values())
            if all_filled or sig.sl_hit:
                to_finalize.append(sig_id)

        # Finalize resolved signals
        for sig_id in to_finalize:
            reason = "sl_hit" if self._active[sig_id].sl_hit else "checkpoints_complete"
            self._finalize_signal(sig_id, reason)

        # Periodic summary save (every 50 updates)
        if self._total_tracked > 0 and self._signal_counter % 50 == 0:
            self._save_summary()

    def _finalize_signal(self, signal_id: str, reason: str) -> None:
        """Write completed signal to disk and remove from active tracking."""
        sig = self._active.pop(signal_id, None)
        if sig is None:
            return

        sig.resolved = True

        # Compute hypothetical PnL
        if sig.tp_scalp_hit and (not sig.sl_hit or (sig.tp_scalp_hit_at or 999999) < (sig.sl_hit_at or 999999)):
            outcome = "WIN_SCALP"
            hypo_pnl = sig.position_size_usd * abs(sig.tp_scalp - sig.entry) / sig.entry
            self._total_tp_scalp_hits += 1
        elif sig.sl_hit:
            outcome = "LOSS"
            hypo_pnl = -sig.risk_amount
            self._total_sl_hits += 1
        else:
            # Time expired — use last price
            if sig.side == "BUY":
                hypo_pnl = sig.position_size_usd * (sig.last_price - sig.entry) / sig.entry
            else:
                hypo_pnl = sig.position_size_usd * (sig.entry - sig.last_price) / sig.entry
            outcome = "TIME_WIN" if hypo_pnl > 0 else "TIME_LOSS"
            self._total_time_expired += 1

        # Update per-setup stats
        setup_key = f"{sig.symbol}_{sig.side}"
        if setup_key not in self._setup_results:
            self._setup_results[setup_key] = {
                "total": 0, "wins": 0, "losses": 0,
                "total_pnl": 0.0, "avg_mfe": 0.0, "avg_mae": 0.0,
            }
        sr = self._setup_results[setup_key]
        sr["total"] += 1
        if "WIN" in outcome:
            sr["wins"] += 1
        else:
            sr["losses"] += 1
        sr["total_pnl"] += hypo_pnl
        sr["avg_mfe"] = (sr["avg_mfe"] * (sr["total"] - 1) + sig.mfe) / sr["total"]
        sr["avg_mae"] = (sr["avg_mae"] * (sr["total"] - 1) + sig.mae) / sr["total"]

        # Write to disk
        record = {
            "signal_id": sig.signal_id,
            "symbol": sig.symbol,
            "side": sig.side,
            "tier": sig.tier,
            "entry": sig.entry,
            "sl": sig.sl,
            "tp_scalp": sig.tp_scalp,
            "confidence": sig.confidence,
            "num_agree": sig.num_agree,
            "regime": sig.regime,
            "is_dip_buy": sig.is_dip_buy,
            "quality_grade": sig.quality_grade,
            "leverage": sig.leverage,
            "risk_amount": sig.risk_amount,
            "position_size_usd": sig.position_size_usd,
            "checkpoints": sig.checkpoints,
            "mfe_pct": round(sig.mfe, 3),
            "mae_pct": round(sig.mae, 3),
            "tp_scalp_hit": sig.tp_scalp_hit,
            "tp_scalp_hit_s": sig.tp_scalp_hit_at,
            "sl_hit": sig.sl_hit,
            "sl_hit_s": sig.sl_hit_at,
            "outcome": outcome,
            "hypo_pnl": round(hypo_pnl, 2),
            "finalize_reason": reason,
            "timestamp": datetime.fromtimestamp(sig.timestamp, tz=timezone.utc).isoformat(),
        }

        try:
            with open(_TRACKER_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[TRACKER] Failed to write signal record: {e}")

        logger.info(
            f"[TRACKER] {sig.signal_id} {sig.symbol} {sig.side} → {outcome} "
            f"PnL=${hypo_pnl:+.2f} MFE={sig.mfe:+.1f}% MAE={sig.mae:+.1f}% "
            f"tp_hit={'Y' if sig.tp_scalp_hit else 'N'} sl_hit={'Y' if sig.sl_hit else 'N'}"
        )

    def _save_summary(self) -> None:
        """Save aggregate summary to disk."""
        total = self._total_tp_scalp_hits + self._total_sl_hits + self._total_time_expired
        if total == 0:
            return

        summary = {
            "total_signals_tracked": self._total_tracked,
            "total_resolved": total,
            "active": len(self._active),
            "tp_scalp_hits": self._total_tp_scalp_hits,
            "sl_hits": self._total_sl_hits,
            "time_expired": self._total_time_expired,
            "win_rate_pct": round(self._total_tp_scalp_hits / total * 100, 1) if total > 0 else 0,
            "by_setup": {
                k: {
                    **v,
                    "wr_pct": round(v["wins"] / v["total"] * 100, 1) if v["total"] > 0 else 0,
                    "avg_pnl": round(v["total_pnl"] / v["total"], 2) if v["total"] > 0 else 0,
                }
                for k, v in self._setup_results.items()
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            tmp = _SUMMARY_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(summary, f, indent=2)
            os.replace(tmp, _SUMMARY_PATH)
        except Exception as e:
            logger.warning(f"[TRACKER] Failed to save summary: {e}")

    def get_report(self) -> Dict[str, Any]:
        """Get current tracking report."""
        total = self._total_tp_scalp_hits + self._total_sl_hits + self._total_time_expired
        return {
            "total_tracked": self._total_tracked,
            "active_signals": len(self._active),
            "resolved": total,
            "tp_hit_rate": round(self._total_tp_scalp_hits / total * 100, 1) if total > 0 else 0,
            "sl_hit_rate": round(self._total_sl_hits / total * 100, 1) if total > 0 else 0,
            "by_setup": dict(self._setup_results),
        }

    def get_active_count(self) -> int:
        return len(self._active)
